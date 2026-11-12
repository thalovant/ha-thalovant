"""Tests for what setup does, and does not do, for Intercom."""

from typing import Any
from unittest.mock import MagicMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.thalovant import async_remove_entry
from custom_components.thalovant.api import ThalovantApiError
from custom_components.thalovant.const import (
    CONF_AGENT_ID,
    CONF_ALLOW_ANNOUNCEMENTS,
    CONF_ALLOW_RECEIVE,
    CONF_CREDENTIALS,
    CONF_TOKENS,
    DOMAIN,
)
from custom_components.thalovant.intercom import can_play_issue_id, unavailable_issue_id
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .conftest import FakeHubConnection, make_intercom_entry


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _nothing_asked(api: MagicMock) -> bool:
    return not any(
        mock.await_count
        for mock in (
            api.announce,
            api.get_announcement,
            api.cancel_announcement,
            api.list_intercom_speakers,
            api.get_intercom_settings,
            api.set_connection_can_play,
        )
    )


async def test_nothing_on_changes_nothing(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
    issue_registry: ir.IssueRegistry,
) -> None:
    """An entry that never turned Intercom on contacts nothing and adds no platform."""
    await _setup(hass, mock_config_entry)
    assert mock_config_entry.runtime_data.platforms == ["binary_sensor"]
    assert _nothing_asked(mock_intercom_api)
    assert list(issue_registry.issues) == []
    assert set(mock_hub_connection.message_callbacks) == {"thalovant.home.request"}


async def test_announcements_on_checks_the_hub(
    hass: HomeAssistant,
    intercom_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
) -> None:
    """Setup reads the hub's Intercom state once, in the background."""
    await _setup(hass, intercom_entry)
    mock_intercom_api.get_intercom_settings.assert_awaited_once_with("hub-maison")
    mock_intercom_api.set_connection_can_play.assert_not_awaited()


async def test_receive_on_tells_the_platform(
    hass: HomeAssistant,
    receive_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
) -> None:
    """Receiving on tells the platform at setup that this connection can play."""
    await _setup(hass, receive_entry)
    mock_intercom_api.set_connection_can_play.assert_awaited_once_with(
        "conn-91c2", True
    )
    mock_intercom_api.get_intercom_settings.assert_not_awaited()


async def test_turning_receive_off_tells_the_platform_and_reloads(
    hass: HomeAssistant,
    receive_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
    issue_registry: ir.IssueRegistry,
) -> None:
    """Saving with receive off says can_play is false, then reloads without the handler."""
    await _setup(hass, receive_entry)
    before = receive_entry.runtime_data
    assert len(mock_hub_connection.message_callbacks["speak"]) == 1

    hass.config_entries.async_update_entry(receive_entry, options={})
    await hass.async_block_till_done()

    mock_intercom_api.set_connection_can_play.assert_awaited_with("conn-91c2", False)
    assert receive_entry.state is ConfigEntryState.LOADED
    assert receive_entry.runtime_data is not before
    assert mock_hub_connection.message_callbacks["speak"] == []
    assert (
        issue_registry.async_get_issue(
            DOMAIN, can_play_issue_id(receive_entry.entry_id)
        )
        is None
    )


async def test_other_options_and_tokens_do_not_reload(
    hass: HomeAssistant,
    intercom_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
) -> None:
    """Changing the agent, or the token, leaves the link running as it was."""
    await _setup(hass, intercom_entry)
    before = intercom_entry.runtime_data

    hass.config_entries.async_update_entry(
        intercom_entry,
        options={**intercom_entry.options, CONF_AGENT_ID: "conversation.other"},
    )
    hass.config_entries.async_update_entry(
        intercom_entry,
        data={**intercom_entry.data, CONF_TOKENS: intercom_entry.data[CONF_TOKENS]},
    )
    await hass.async_block_till_done()
    assert intercom_entry.runtime_data is before
    mock_hub_connection.connect.assert_awaited_once()


async def test_turning_announcements_off_clears_the_notice(
    hass: HomeAssistant,
    credentials: Any,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
    issue_registry: ir.IssueRegistry,
) -> None:
    """A notice about Intercom does not outlive the option that caused it."""
    entry = make_intercom_entry(credentials, options={CONF_ALLOW_ANNOUNCEMENTS: True})
    entry.add_to_hass(hass)
    ir.async_create_issue(
        hass,
        DOMAIN,
        unavailable_issue_id(entry.entry_id),
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="intercom_unavailable_plan",
    )
    ir.async_create_issue(
        hass,
        DOMAIN,
        can_play_issue_id(entry.entry_id),
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="intercom_can_play",
    )
    hass.config_entries.async_update_entry(entry, options={})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert (
        issue_registry.async_get_issue(DOMAIN, unavailable_issue_id(entry.entry_id))
        is None
    )
    assert (
        issue_registry.async_get_issue(DOMAIN, can_play_issue_id(entry.entry_id))
        is None
    )


async def test_a_failed_can_play_leaves_a_notice_and_the_entry_loaded(
    hass: HomeAssistant,
    receive_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
    issue_registry: ir.IssueRegistry,
) -> None:
    """The platform not taking the change is shown in Repairs, not raised."""
    mock_intercom_api.set_connection_can_play.side_effect = ThalovantApiError(
        status=422
    )
    await _setup(hass, receive_entry)
    assert receive_entry.state is ConfigEntryState.LOADED
    issue = issue_registry.async_get_issue(
        DOMAIN, can_play_issue_id(receive_entry.entry_id)
    )
    assert issue is not None
    assert issue.translation_key == "intercom_can_play"


async def test_removing_the_entry_removes_its_notices(
    hass: HomeAssistant,
    intercom_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
    mock_api: MagicMock,
    issue_registry: ir.IssueRegistry,
) -> None:
    """Nothing about Intercom is left in Repairs after the link is removed."""
    await _setup(hass, intercom_entry)
    for issue_id in (
        unavailable_issue_id(intercom_entry.entry_id),
        can_play_issue_id(intercom_entry.entry_id),
    ):
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="intercom_can_play",
        )
    await async_remove_entry(hass, intercom_entry)
    assert list(issue_registry.issues) == []


async def test_the_stored_entry_has_no_intercom_keys_until_turned_on(
    mock_config_entry: MockConfigEntry,
) -> None:
    """Documentation of what is stored: the options hold no Intercom key by default."""
    assert mock_config_entry.options == {}
    assert CONF_ALLOW_RECEIVE not in mock_config_entry.data
    assert CONF_CREDENTIALS in mock_config_entry.data


@pytest.mark.usefixtures("mock_intercom_api")
async def test_services_survive_a_reload(
    hass: HomeAssistant,
    intercom_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
) -> None:
    """The actions are registered once, and a reload does not lose them."""
    await _setup(hass, intercom_entry)
    assert await hass.config_entries.async_reload(intercom_entry.entry_id)
    assert hass.services.has_service(DOMAIN, "announce")
