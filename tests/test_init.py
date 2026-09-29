"""Tests for setting up and removing a Thalovant entry."""

import asyncio
from collections.abc import Callable
import logging
from pathlib import Path
from unittest.mock import MagicMock

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.thalovant import (
    _noise_dir_name,
    _token_in_use,
    key_changed_issue_id,
    key_rejected_issue_id,
)
from custom_components.thalovant.api import (
    ThalovantAuthError,
    ThalovantClientKeyRejectedError,
    ThalovantConnectionError,
    ThalovantError,
    ThalovantHubKeyChangedError,
    Tokens,
)
from custom_components.thalovant.const import (
    CONF_ACCOUNT_ID,
    CONF_CREDENTIALS,
    CONF_LINKED_AT,
    CONF_TOKENS,
    DOMAIN,
    REQUEST_MESSAGE_TYPE,
)
from custom_components.thalovant.handler import agent_issue_id
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .conftest import ACCOUNT_ID, CONNECTION_ID, OTHER_HUB_ID, FakeHubConnection


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
    # The Noise keys live with Home Assistant's own storage, one folder per
    # connection, so re-linking starts with a new key and no pin.
    assert mock_hub_connection.factory.call_args.kwargs == {
        "state_dir": hass.config.path(".storage", "thalovant", CONNECTION_ID)
    }
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
    """Removing the entry deletes its connection, revokes its token, drops its issue."""
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
    mock_api.revoke_token.assert_awaited_once_with()
    assert [name for name, *_ in mock_api.method_calls[-2:]] == [
        "delete_connection",
        "revoke_token",
    ]
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
    mock_api.revoke_token.side_effect = side_effect
    await _setup(hass, mock_config_entry)
    await hass.config_entries.async_remove(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.config_entries.async_entries(DOMAIN) == []
    # A failed delete does not stop the revocation, and both are said.
    mock_api.revoke_token.assert_awaited_once_with()
    assert "Could not delete the Home Assistant connection on Maison" in caplog.text
    assert "Could not revoke the Thalovant API token of Maison" in caplog.text


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


@pytest.mark.parametrize(
    "refusal",
    [
        ThalovantAuthError("unknown key"),
        # Even one that names the key: a hub that has not admitted the
        # connection yet has pinned nothing to compare it with.
        ThalovantClientKeyRejectedError("key rejected"),
    ],
)
async def test_refusal_right_after_linking_retries(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    freezer: FrozenDateTimeFactory,
    issue_registry: ir.IssueRegistry,
    refusal: ThalovantAuthError,
) -> None:
    """A new connection the hub refuses is not admitted yet: retry, no reauth."""
    freezer.move_to("2026-09-27T12:05:00+00:00")
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        data={**mock_config_entry.data, CONF_LINKED_AT: "2026-09-27T12:00:00+00:00"},
    )
    mock_hub_connection.connect.side_effect = refusal
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY
    assert (
        mock_config_entry.reason
        == "The hub Maison has not admitted this connection yet"
    )
    assert hass.config_entries.flow.async_progress_by_handler(DOMAIN) == []
    assert not issue_registry.issues


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


async def test_remove_with_unreadable_token(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_api: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Without a readable token nothing can be cleaned up remotely; removal goes on."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, data={**mock_config_entry.data, CONF_TOKENS: None}
    )
    await hass.config_entries.async_remove(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.config_entries.async_entries(DOMAIN) == []
    mock_api.delete_connection.assert_not_awaited()
    assert "The stored Thalovant token for Maison cannot be read" in caplog.text


async def test_hub_key_changed_at_setup(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    issue_registry: ir.IssueRegistry,
) -> None:
    """A changed hub key is no blip: it raises a repair issue and asks to re-link."""
    mock_hub_connection.connect.side_effect = ThalovantHubKeyChangedError("changed")
    await _setup(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    issue = issue_registry.async_get_issue(
        DOMAIN, key_changed_issue_id(mock_config_entry.entry_id)
    )
    assert issue is not None
    assert issue.severity is ir.IssueSeverity.ERROR
    assert issue.translation_key == "hub_key_changed"
    assert issue.translation_placeholders == {"hub": "Maison"}
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]


async def test_hub_key_changed_while_running(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    issue_registry: ir.IssueRegistry,
) -> None:
    """A key that changes after setup stops the link and asks to re-link."""
    changed = asyncio.Event()

    async def run() -> None:
        await changed.wait()
        raise ThalovantHubKeyChangedError("changed")

    mock_hub_connection.run.side_effect = run
    await _setup(hass, mock_config_entry)
    issue_id = key_changed_issue_id(mock_config_entry.entry_id)
    assert issue_registry.async_get_issue(DOMAIN, issue_id) is None

    changed.set()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert issue_registry.async_get_issue(DOMAIN, issue_id) is not None
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]


async def test_client_key_rejected_at_setup(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    issue_registry: ir.IssueRegistry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A hub that refuses this installation's key: a repair issue, then re-link."""
    mock_hub_connection.connect.side_effect = ThalovantClientKeyRejectedError(
        "The hub refused this client's Noise key"
    )
    await _setup(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    assert mock_config_entry.reason == (
        "The hub Maison refused this Home Assistant's security key for the link"
    )
    issue = issue_registry.async_get_issue(
        DOMAIN, key_rejected_issue_id(mock_config_entry.entry_id)
    )
    assert issue is not None
    assert issue.severity is ir.IssueSeverity.ERROR
    assert issue.translation_key == "client_key_rejected"
    assert issue.translation_placeholders == {"hub": "Maison"}
    assert "re-link it to make a new connection" in caplog.text
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]


async def test_client_key_rejected_while_running(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    issue_registry: ir.IssueRegistry,
) -> None:
    """The SDK stops the link at once on a refused key; the entry asks to re-link."""
    rejected = asyncio.Event()

    async def run() -> None:
        await rejected.wait()
        raise ThalovantClientKeyRejectedError("rejected")

    mock_hub_connection.run.side_effect = run
    await _setup(hass, mock_config_entry)
    issue_id = key_rejected_issue_id(mock_config_entry.entry_id)
    assert issue_registry.async_get_issue(DOMAIN, issue_id) is None

    rejected.set()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert issue_registry.async_get_issue(DOMAIN, issue_id) is not None
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]


@pytest.mark.parametrize(
    ("issue_id", "translation_key"),
    [
        (key_changed_issue_id, "hub_key_changed"),
        (key_rejected_issue_id, "client_key_rejected"),
    ],
)
async def test_relinked_hub_clears_the_issue(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    issue_registry: ir.IssueRegistry,
    issue_id: Callable[[str], str],
    translation_key: str,
) -> None:
    """Once the link connects again, the issue about keys goes away."""
    issue = issue_id(mock_config_entry.entry_id)
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue,
        is_fixable=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key=translation_key,
    )
    await _setup(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert issue_registry.async_get_issue(DOMAIN, issue) is None


async def test_remove_keeps_a_token_other_links_use(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_api: MagicMock,
) -> None:
    """The account's token is revoked with the last entry that signs in with it."""
    other = MockConfigEntry(
        domain=DOMAIN,
        title="Daily Desk",
        unique_id=f"{ACCOUNT_ID}:{OTHER_HUB_ID}",
        data={
            **mock_config_entry.data,
            CONF_CREDENTIALS: {
                **mock_config_entry.data[CONF_CREDENTIALS],
                "connection_id": "conn-desk",
            },
        },
    )
    await _setup(hass, mock_config_entry)
    await _setup(hass, other)

    await hass.config_entries.async_remove(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    mock_api.delete_connection.assert_awaited_once_with(CONNECTION_ID)
    mock_api.revoke_token.assert_not_awaited()

    await hass.config_entries.async_remove(other.entry_id)
    await hass.async_block_till_done()
    mock_api.delete_connection.assert_awaited_with("conn-desk")
    mock_api.revoke_token.assert_awaited_once_with()


def test_token_in_use(hass: HomeAssistant, mock_config_entry: MockConfigEntry) -> None:
    """Only another entry holding the same token keeps it; the removed one does not."""
    mock_config_entry.add_to_hass(hass)
    tokens = Tokens.from_dict(mock_config_entry.data[CONF_TOKENS])
    assert _token_in_use(hass, mock_config_entry, tokens) is False

    unreadable = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"{ACCOUNT_ID}:{OTHER_HUB_ID}",
        data={CONF_ACCOUNT_ID: ACCOUNT_ID, CONF_TOKENS: "not a mapping"},
    )
    unreadable.add_to_hass(hass)
    assert _token_in_use(hass, mock_config_entry, tokens) is False

    sharing = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"{ACCOUNT_ID}:hub-third",
        data={CONF_ACCOUNT_ID: ACCOUNT_ID, CONF_TOKENS: tokens.to_dict()},
    )
    sharing.add_to_hass(hass)
    assert _token_in_use(hass, mock_config_entry, tokens) is True


async def test_noise_folders_follow_the_connections(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_api: MagicMock,
) -> None:
    """Folders of connections no entry uses are pruned; removal deletes the entry's."""
    root = Path(hass.config.path(".storage", "thalovant"))
    await hass.async_add_executor_job(_make_noise_state, root)
    await _setup(hass, mock_config_entry)
    # The re-linked-away connection and the old shared store are gone.
    assert sorted(await hass.async_add_executor_job(_names, root)) == [CONNECTION_ID]

    await hass.config_entries.async_remove(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.async_add_executor_job(_names, root) == []


async def test_prune_without_a_store(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
) -> None:
    """With nothing stored yet there is nothing to prune."""
    await _setup(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.LOADED


def test_noise_dir_names() -> None:
    """A connection id never escapes the store's folder."""
    assert _noise_dir_name("conn-91c2_x") == "conn-91c2_x"
    assert _noise_dir_name("../../etc") == "______etc"
    assert _noise_dir_name("") == "_"


def _make_noise_state(root: Path) -> None:
    (root / CONNECTION_ID).mkdir(parents=True)
    (root / CONNECTION_ID / "_identity.json").write_text("{}")
    (root / "conn-old").mkdir()
    (root / "_identity.json").write_text("{}")


def _names(root: Path) -> list[str]:
    return [child.name for child in root.iterdir()] if root.is_dir() else []


async def test_remove_with_unreadable_credentials(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_api: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An entry whose credentials cannot be read is still removed, token revoked."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, data={**mock_config_entry.data, CONF_CREDENTIALS: None}
    )
    await hass.config_entries.async_remove(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.config_entries.async_entries(DOMAIN) == []
    mock_api.delete_connection.assert_not_awaited()
    mock_api.revoke_token.assert_awaited_once_with()
    assert "Could not delete the Home Assistant connection on Maison" in caplog.text
