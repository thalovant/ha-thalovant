"""Tests for setting up and removing a Thalovant entry."""

import asyncio
import logging
from unittest.mock import MagicMock

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.thalovant.api import (
    ThalovantAuthError,
    ThalovantConnectionError,
    ThalovantError,
)
from custom_components.thalovant.const import (
    CONF_CREDENTIALS,
    CONF_LINKED_AT,
    DOMAIN,
    REQUEST_MESSAGE_TYPE,
)
from custom_components.thalovant.handler import agent_issue_id
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .conftest import CONNECTION_ID, FakeHubConnection


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_setup_and_unload(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
) -> None:
    """The entry connects, listens for requests, and lets go on unload."""
    await _setup(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert mock_config_entry.runtime_data.connection is mock_hub_connection
    credentials = mock_hub_connection.factory.call_args.args[1]
    assert credentials.connection_id == CONNECTION_ID
    mock_hub_connection.connect.assert_awaited_once()
    mock_hub_connection.run.assert_awaited_once()
    assert len(mock_hub_connection.message_callbacks[REQUEST_MESSAGE_TYPE]) == 1

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED
    mock_hub_connection.close.assert_awaited_once()
    assert mock_hub_connection.message_callbacks[REQUEST_MESSAGE_TYPE] == []
    assert mock_hub_connection.state_callbacks == []


async def test_setup_retries_when_hub_unreachable(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
) -> None:
    """An unreachable hub means try again later, with nothing left behind."""
    mock_hub_connection.connect.side_effect = ThalovantConnectionError("refused")
    await _setup(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY
    assert mock_config_entry.reason == "Could not reach the hub Maison"
    mock_hub_connection.close.assert_awaited_once()
    assert mock_hub_connection.message_callbacks[REQUEST_MESSAGE_TYPE] == []
    assert mock_hub_connection.state_callbacks == []


async def test_setup_starts_reauth_when_rejected(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
) -> None:
    """Rejected credentials start the reauth flow."""
    mock_hub_connection.connect.side_effect = ThalovantAuthError("bad key")
    await _setup(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert len(flows) == 1
    assert flows[0]["context"]["source"] == SOURCE_REAUTH
    assert flows[0]["context"]["entry_id"] == mock_config_entry.entry_id


async def test_rejected_while_running_starts_reauth(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
) -> None:
    """Credentials revoked after setup start the reauth flow too."""
    rejected = asyncio.Event()

    async def run() -> None:
        await rejected.wait()
        raise ThalovantAuthError("revoked")

    mock_hub_connection.run.side_effect = run
    await _setup(hass, mock_config_entry)
    assert hass.config_entries.flow.async_progress_by_handler(DOMAIN) == []

    rejected.set()
    await hass.async_block_till_done(wait_background_tasks=True)
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert len(flows) == 1
    assert flows[0]["context"]["source"] == SOURCE_REAUTH


async def test_run_failure_is_logged(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An unexpected end of the connection loop is logged, not raised."""
    mock_hub_connection.run.side_effect = RuntimeError("library bug")
    await _setup(hass, mock_config_entry)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert "The connection to Maison stopped" in caplog.text


async def test_state_changes_are_logged_once(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A drop and a recovery are each logged once, at info."""
    await _setup(hass, mock_config_entry)
    caplog.clear()
    caplog.set_level(logging.INFO, logger="custom_components.thalovant")

    mock_hub_connection.set_connected(False)
    mock_hub_connection.set_connected(False)
    mock_hub_connection.set_connected(True)
    mock_hub_connection.set_connected(True)

    messages = [
        record.getMessage()
        for record in caplog.records
        if record.name == "custom_components.thalovant"
    ]
    assert messages == [
        "Lost the connection to Maison; reconnecting",
        "Reconnected to Maison",
    ]


async def test_remove_deletes_connection(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_api: MagicMock,
    issue_registry: ir.IssueRegistry,
) -> None:
    """Removing the entry deletes its connection on the hub and its issue."""
    await _setup(hass, mock_config_entry)
    issue_id = agent_issue_id(mock_config_entry.entry_id)
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="agent_unavailable",
    )
    await hass.config_entries.async_remove(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    mock_api.delete_connection.assert_awaited_once_with(CONNECTION_ID)
    assert hass.config_entries.async_entries(DOMAIN) == []
    assert issue_registry.async_get_issue(DOMAIN, issue_id) is None


@pytest.mark.parametrize(
    "side_effect",
    [ThalovantError("401"), ThalovantConnectionError("dns"), TimeoutError()],
)
async def test_remove_survives_api_failure(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_api: MagicMock,
    caplog: pytest.LogCaptureFixture,
    side_effect: Exception,
) -> None:
    """Removal goes through even when the control plane cannot be reached."""
    mock_api.delete_connection.side_effect = side_effect
    await _setup(hass, mock_config_entry)
    await hass.config_entries.async_remove(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.config_entries.async_entries(DOMAIN) == []
    assert "remove it from the Thalovant dashboard" in caplog.text


async def test_unreadable_credentials_start_reauth(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
) -> None:
    """Stored credentials that cannot be read are renewed through reauth."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        data={**mock_config_entry.data, CONF_CREDENTIALS: {"secret": None}},
    )
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    mock_hub_connection.factory.assert_not_called()
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]


async def test_refusal_right_after_linking_retries(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A new connection the hub refuses is not admitted yet: retry, no reauth."""
    freezer.move_to("2026-09-27T12:05:00+00:00")
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        data={**mock_config_entry.data, CONF_LINKED_AT: "2026-09-27T12:00:00+00:00"},
    )
    mock_hub_connection.connect.side_effect = ThalovantAuthError("unknown key")
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY
    assert (
        mock_config_entry.reason
        == "The hub Maison has not admitted this connection yet"
    )
    assert hass.config_entries.flow.async_progress_by_handler(DOMAIN) == []


async def test_refusal_after_grace_starts_reauth(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Past the grace period, a refusal means the credentials are bad."""
    freezer.move_to("2026-09-27T12:11:00+00:00")
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        data={**mock_config_entry.data, CONF_LINKED_AT: "2026-09-27T12:00:00+00:00"},
    )
    mock_hub_connection.connect.side_effect = ThalovantAuthError("bad key")
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]
