"""Tests for the Thalovant config flow."""

import asyncio
from dataclasses import replace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.thalovant.api import (
    Account,
    ConnectionCredentials,
    DeviceLogin,
    DeviceLoginDenied,
    DeviceLoginExpired,
    DeviceLoginPending,
    Hub,
    ThalovantAdmissionFailedError,
    ThalovantAdmissionTimeoutError,
    ThalovantAlreadyLinkedError,
    ThalovantApiError,
    ThalovantAuthError,
    ThalovantConnectionError,
    ThalovantError,
    ThalovantPlanError,
    ThalovantUnsupportedError,
    Tokens,
)
from custom_components.thalovant.const import (
    ADMISSION_TIMEOUT,
    CONF_ACCOUNT_ID,
    CONF_AGENT_ID,
    CONF_CREDENTIALS,
    CONF_HUB_ID,
    CONF_HUB_NAME,
    CONF_LINKED_AT,
    CONF_TOKENS,
    CONNECTION_KIND,
    DOMAIN,
    LOGIN_SCOPES,
)
from custom_components.thalovant.handler import agent_issue_id
from homeassistant.components import conversation
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, UnknownFlow
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component

from .conftest import ACCOUNT_ID, CONNECTION_ID, HUB_ID, OTHER_HUB_ID

pytestmark = pytest.mark.usefixtures("mock_setup_entry")


async def _start(hass: HomeAssistant) -> dict[str, Any]:
    """Open the flow and submit the first step."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}
    return await hass.config_entries.flow.async_configure(result["flow_id"], {})


async def _finish_progress(
    hass: HomeAssistant, result: dict[str, Any], step_id: str
) -> dict[str, Any]:
    """Let a progress step's task end and move past it."""
    assert result["type"] is FlowResultType.SHOW_PROGRESS, result
    assert result["step_id"] == step_id
    await hass.async_block_till_done()
    return await hass.config_entries.flow.async_configure(result["flow_id"])


async def _finish_login(hass: HomeAssistant, result: dict[str, Any]) -> dict[str, Any]:
    return await _finish_progress(hass, result, "login")


async def _pick_hub(
    hass: HomeAssistant, result: dict[str, Any], hub_id: str = HUB_ID
) -> dict[str, Any]:
    assert result["type"] is FlowResultType.FORM, result
    assert result["step_id"] == "hub"
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HUB_ID: hub_id}
    )


async def _finish_admission(
    hass: HomeAssistant, result: dict[str, Any]
) -> dict[str, Any]:
    return await _finish_progress(hass, result, "admission")


async def test_full_flow(
    hass: HomeAssistant,
    mock_auth: MagicMock,
    mock_api: MagicMock,
    mock_setup_entry: AsyncMock,
    tokens: Tokens,
    credentials: ConnectionCredentials,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Sign in, pick a hub, wait for it to admit us, and store the connection."""
    freezer.move_to("2026-09-27T12:00:00+00:00")
    hass.config.location_name = "Home"
    result = await _start(hass)

    assert result["type"] is FlowResultType.SHOW_PROGRESS
    assert result["progress_action"] == "wait_for_login"
    assert result["description_placeholders"] == {
        "url": "https://dash.thalovant.com/device?code=WXYZ-2345",
        "code": "WXYZ-2345",
    }
    mock_auth.start_device_login.assert_awaited_once_with(
        client_name="Home Assistant (Home)", scopes=LOGIN_SCOPES
    )
    assert LOGIN_SCOPES == ("hubs:read", "clients:read", "clients:write")

    result = await _finish_login(hass, result)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "hub"
    assert result["description_placeholders"] == {"account": "Gaëtan"}
    options = result["data_schema"].schema[CONF_HUB_ID].config["options"]
    assert [option["label"] for option in options] == ["Daily Desk", "Maison"]

    result = await _pick_hub(hass, result)
    assert result["type"] is FlowResultType.SHOW_PROGRESS
    assert result["progress_action"] == "wait_for_admission"
    assert result["description_placeholders"] == {"hub": "Maison"}
    mock_api.create_connection.assert_awaited_once_with(
        HUB_ID, name="Home Assistant (Maison)", kind=CONNECTION_KIND
    )
    assert CONNECTION_KIND == "home_assistant"

    result = await _finish_admission(hass, result)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Maison"
    assert result["result"].unique_id == f"{ACCOUNT_ID}:{HUB_ID}"
    assert result["data"] == {
        CONF_ACCOUNT_ID: ACCOUNT_ID,
        CONF_HUB_ID: HUB_ID,
        CONF_HUB_NAME: "Maison",
        CONF_TOKENS: tokens.to_dict(),
        CONF_CREDENTIALS: credentials.to_dict(),
        CONF_LINKED_AT: "2026-09-27T12:00:00+00:00",
    }
    mock_api.wait_for_admission.assert_awaited_once_with(
        credentials, timeout=ADMISSION_TIMEOUT
    )
    mock_api.delete_connection.assert_not_awaited()
    assert len(mock_setup_entry.mock_calls) == 1
    # The entry holds the token now: it is not revoked.
    await hass.async_block_till_done(wait_background_tasks=True)
    mock_api.revoke_token.assert_not_awaited()


async def test_verification_uri_without_code(
    hass: HomeAssistant, mock_auth: MagicMock, device_login: DeviceLogin
) -> None:
    """Without a complete URI the plain one is shown beside the code."""
    mock_auth.start_device_login.return_value = replace(
        device_login, verification_uri_complete=None
    )
    mock_auth.poll_device_login.side_effect = DeviceLoginPending(interval=0)
    result = await _start(hass)
    assert (
        result["description_placeholders"]["url"] == "https://dash.thalovant.com/device"
    )
    hass.config_entries.flow.async_abort(result["flow_id"])


async def test_account_without_display_name(
    hass: HomeAssistant, mock_auth: MagicMock, mock_api: MagicMock
) -> None:
    """The hub step names the account by email when it has no display name."""
    mock_api.get_account.return_value = Account(
        id=ACCOUNT_ID, display_name=None, email="gaetan@example.com"
    )
    result = await _finish_login(hass, await _start(hass))
    assert result["description_placeholders"] == {"account": "gaetan@example.com"}


@pytest.mark.parametrize(
    ("side_effect", "error"),
    [
        (ThalovantConnectionError("dns"), "cannot_connect"),
        (RuntimeError("boom"), "unknown"),
    ],
)
async def test_start_login_errors(
    hass: HomeAssistant,
    mock_auth: MagicMock,
    mock_api: MagicMock,
    side_effect: Exception,
    error: str,
) -> None:
    """A failed start shows the error and the next submit starts again."""
    mock_auth.start_device_login.side_effect = side_effect
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": error}

    mock_auth.start_device_login.side_effect = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    result = await _pick_hub(hass, await _finish_login(hass, result))
    result = await _finish_admission(hass, result)
    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.parametrize(
    ("side_effect", "error"),
    [
        (DeviceLoginExpired(), "login_expired"),
        (DeviceLoginDenied(), "login_denied"),
        (ThalovantConnectionError("reset"), "cannot_connect"),
        (RuntimeError("boom"), "unknown"),
    ],
)
async def test_login_errors(
    hass: HomeAssistant,
    mock_auth: MagicMock,
    mock_api: MagicMock,
    tokens: Tokens,
    side_effect: Exception,
    error: str,
) -> None:
    """A failed sign-in goes back to the first step, which can start again."""
    mock_auth.poll_device_login.side_effect = side_effect
    result = await _finish_login(hass, await _start(hass))
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": error}

    mock_auth.poll_device_login.side_effect = None
    mock_auth.poll_device_login.return_value = tokens
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    result = await _pick_hub(hass, await _finish_login(hass, result))
    result = await _finish_admission(hass, result)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_login_pending_and_slow_down(
    hass: HomeAssistant, mock_auth: MagicMock, mock_api: MagicMock, tokens: Tokens
) -> None:
    """Pending keeps polling; slow_down's longer interval is adopted."""
    sleeps: list[float] = []
    real_sleep = asyncio.sleep

    async def record_sleep(delay: float, *args: Any) -> Any:
        sleeps.append(delay)
        return await real_sleep(0)

    mock_auth.poll_device_login.side_effect = [
        DeviceLoginPending(interval=0),
        DeviceLoginPending(interval=7),
        DeviceLoginPending(interval=0),
        tokens,
    ]
    with patch(
        "custom_components.thalovant.config_flow.asyncio.sleep",
        side_effect=record_sleep,
    ):
        result = await _finish_login(hass, await _start(hass))
    assert result["step_id"] == "hub"
    assert mock_auth.poll_device_login.await_count == 4
    # Other code sleeps too while patched; the flow's own non-zero waits are 7, 7.
    assert [delay for delay in sleeps if delay] == [7, 7]


async def test_login_expires_locally(
    hass: HomeAssistant,
    mock_auth: MagicMock,
    mock_api: MagicMock,
    device_login: DeviceLogin,
) -> None:
    """A code the server keeps calling pending still expires on time."""
    mock_auth.start_device_login.return_value = replace(device_login, expires_in=0)
    mock_auth.poll_device_login.side_effect = DeviceLoginPending(interval=0)
    result = await _finish_login(hass, await _start(hass))
    assert result["errors"] == {"base": "login_expired"}
    assert mock_auth.poll_device_login.await_count == 1


async def test_flow_removed_while_waiting(
    hass: HomeAssistant, mock_auth: MagicMock
) -> None:
    """Closing the dialog stops the polling."""
    mock_auth.poll_device_login.side_effect = DeviceLoginPending(interval=0)
    result = await _start(hass)
    assert result["type"] is FlowResultType.SHOW_PROGRESS

    hass.config_entries.flow.async_abort(result["flow_id"])
    await hass.async_block_till_done()
    with pytest.raises(UnknownFlow):
        hass.config_entries.flow.async_get(result["flow_id"])


@pytest.mark.parametrize(
    ("side_effect", "error"),
    [
        (ThalovantAuthError("401"), "invalid_auth"),
        (ThalovantConnectionError("503"), "cannot_connect"),
        (RuntimeError("boom"), "unknown"),
    ],
)
async def test_account_errors(
    hass: HomeAssistant,
    mock_auth: MagicMock,
    mock_api: MagicMock,
    side_effect: Exception,
    error: str,
) -> None:
    """Reading the account fails back to the first step."""
    mock_api.list_hubs.side_effect = side_effect
    result = await _finish_login(hass, await _start(hass))
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": error}

    mock_api.list_hubs.side_effect = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    if error == "invalid_auth":
        # A rejected token is thrown away: this submit signs in again.
        result = await _finish_login(hass, result)
        assert mock_auth.start_device_login.await_count == 2
    else:
        # A token that still works is reused instead of minting another.
        assert mock_auth.start_device_login.await_count == 1
    assert result["step_id"] == "hub"


async def test_no_hubs(
    hass: HomeAssistant, mock_auth: MagicMock, mock_api: MagicMock
) -> None:
    """An account without a hub cannot be linked."""
    mock_api.list_hubs.return_value = []
    result = await _finish_login(hass, await _start(hass))
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_hubs"
    # The token minted for nothing is revoked: a Free plan allows one.
    await hass.async_block_till_done(wait_background_tasks=True)
    mock_api.revoke_token.assert_awaited_once_with()


async def test_unused_token_revoke_fails(
    hass: HomeAssistant,
    mock_auth: MagicMock,
    mock_api: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A token that cannot be revoked is named in the log."""
    mock_api.list_hubs.return_value = []
    mock_api.revoke_token.side_effect = ThalovantConnectionError("down")
    result = await _finish_login(hass, await _start(hass))
    assert result["reason"] == "no_hubs"
    await hass.async_block_till_done(wait_background_tasks=True)
    assert "Could not revoke the unused Thalovant API token" in caplog.text


async def test_new_token_moves_the_accounts_links_to_it(
    hass: HomeAssistant,
    mock_auth: MagicMock,
    mock_api: MagicMock,
    mock_config_entry: MockConfigEntry,
    tokens: Tokens,
) -> None:
    """Approving Home Assistant again revokes the token the account's links hold.

    Each entry of the account gets the new token, the old one is revoked in
    case it was still alive, and the flow no longer revokes the new token
    when it ends without a link: the entries hold it.
    """
    old = Tokens("old-access", None, ("hubs:read",), "tok-old")
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, data={**mock_config_entry.data, CONF_TOKENS: old.to_dict()}
    )
    unreadable = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"{ACCOUNT_ID}:hub-third",
        data={**mock_config_entry.data, CONF_HUB_ID: "hub-third", CONF_TOKENS: None},
    )
    unreadable.add_to_hass(hass)
    stranger_tokens = Tokens("stranger-access", None, (), "tok-stranger").to_dict()
    stranger = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"acct-other:{HUB_ID}",
        data={
            **mock_config_entry.data,
            CONF_ACCOUNT_ID: "acct-other",
            CONF_TOKENS: stranger_tokens,
        },
    )
    stranger.add_to_hass(hass)

    with patch(
        "custom_components.thalovant.config_flow.ThalovantApi", return_value=mock_api
    ) as api_class:
        result = await _finish_login(hass, await _start(hass))
        assert result["step_id"] == "hub"
        assert mock_config_entry.data[CONF_TOKENS] == tokens.to_dict()
        assert unreadable.data[CONF_TOKENS] == tokens.to_dict()
        assert stranger.data[CONF_TOKENS] == stranger_tokens
        await hass.async_block_till_done(wait_background_tasks=True)
        mock_api.revoke_token.assert_awaited_once_with()
        assert api_class.call_args_list[-1].args[1] == old

        hass.config_entries.flow.async_abort(result["flow_id"])
        await hass.async_block_till_done(wait_background_tasks=True)
    mock_api.revoke_token.assert_awaited_once_with()


async def test_linked_hubs_are_not_offered(
    hass: HomeAssistant,
    mock_auth: MagicMock,
    mock_api: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A hub already linked for this account is left out of the picker."""
    mock_config_entry.add_to_hass(hass)
    result = await _finish_login(hass, await _start(hass))
    options = result["data_schema"].schema[CONF_HUB_ID].config["options"]
    assert [option["value"] for option in options] == [OTHER_HUB_ID]


async def test_all_hubs_linked(
    hass: HomeAssistant,
    mock_auth: MagicMock,
    mock_api: MagicMock,
    mock_config_entry: MockConfigEntry,
    hubs: list[Hub],
) -> None:
    """Nothing left to link aborts."""
    mock_config_entry.add_to_hass(hass)
    mock_api.list_hubs.return_value = [hubs[0]]
    result = await _finish_login(hass, await _start(hass))
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "all_hubs_linked"


async def test_duplicate_entry_aborts(
    hass: HomeAssistant,
    mock_auth: MagicMock,
    mock_api: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A hub linked while the picker was open is not linked twice."""
    result = await _finish_login(hass, await _start(hass))
    assert result["step_id"] == "hub"

    mock_config_entry.add_to_hass(hass)
    result = await _pick_hub(hass, result)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    mock_api.create_connection.assert_not_awaited()


@pytest.mark.parametrize(
    ("side_effect", "error"),
    [
        (ThalovantConnectionError("503"), "cannot_connect"),
        (ThalovantPlanError("Payment required", status=402), "public_hubs_only"),
        (
            ThalovantPlanError(
                "Free plan allows up to 1 connection.", status=403, code="plan_limit"
            ),
            "plan_limit",
        ),
        (
            ThalovantAlreadyLinkedError(
                "Conflict",
                status=409,
                code="home_assistant_already_linked",
                connection_id="conn-other",
            ),
            "already_linked",
        ),
        (ThalovantUnsupportedError("Unprocessable", status=422), "hub_cannot_link"),
        (ThalovantApiError("Name taken", status=400), "connection_refused"),
        (ThalovantError("no status"), "connection_refused"),
        (RuntimeError("boom"), "unknown"),
    ],
)
async def test_create_connection_errors(
    hass: HomeAssistant,
    mock_auth: MagicMock,
    mock_api: MagicMock,
    credentials: ConnectionCredentials,
    side_effect: Exception,
    error: str,
) -> None:
    """A refused connection keeps the picker open with the reason."""
    mock_api.create_connection.side_effect = side_effect
    result = await _pick_hub(hass, await _finish_login(hass, await _start(hass)))
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "hub"
    assert result["errors"] == {"base": error}

    mock_api.create_connection.side_effect = None
    mock_api.create_connection.return_value = credentials
    result = await _finish_admission(hass, await _pick_hub(hass, result, OTHER_HUB_ID))
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Daily Desk"


async def test_rejected_token_is_not_revoked(
    hass: HomeAssistant, mock_auth: MagicMock, mock_api: MagicMock
) -> None:
    """A token the API rejected is dropped, not revoked, when the flow closes."""
    mock_api.create_connection.side_effect = ThalovantAuthError("401")
    result = await _pick_hub(hass, await _finish_login(hass, await _start(hass)))
    assert result["errors"] == {"base": "invalid_auth"}
    hass.config_entries.flow.async_abort(result["flow_id"])
    await hass.async_block_till_done(wait_background_tasks=True)
    mock_api.revoke_token.assert_not_awaited()


async def test_create_connection_auth_error(
    hass: HomeAssistant, mock_auth: MagicMock, mock_api: MagicMock
) -> None:
    """A token rejected at the last step means signing in again."""
    mock_api.create_connection.side_effect = ThalovantAuthError("401")
    result = await _pick_hub(hass, await _finish_login(hass, await _start(hass)))
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "invalid_auth"}


@pytest.mark.parametrize(
    ("side_effect", "error", "step_id"),
    [
        (ThalovantAdmissionTimeoutError("not yet"), "admission_timeout", "hub"),
        (TimeoutError(), "admission_timeout", "hub"),
        (ThalovantConnectionError("reset"), "cannot_connect", "hub"),
        (ThalovantAdmissionFailedError("operation failed"), "admission_failed", "hub"),
        (ThalovantApiError("operation failed"), "admission_failed", "hub"),
        (RuntimeError("boom"), "unknown", "hub"),
        (ThalovantAuthError("401"), "invalid_auth", "user"),
    ],
)
async def test_admission_errors(
    hass: HomeAssistant,
    mock_auth: MagicMock,
    mock_api: MagicMock,
    side_effect: Exception,
    error: str,
    step_id: str,
) -> None:
    """A connection the hub never admits is deleted, and the user can try again."""
    mock_api.wait_for_admission.side_effect = side_effect
    result = await _pick_hub(hass, await _finish_login(hass, await _start(hass)))
    result = await _finish_admission(hass, result)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == step_id
    assert result["errors"] == {"base": error}
    mock_api.delete_connection.assert_awaited_once_with(CONNECTION_ID)


async def test_admission_error_and_delete_fails(
    hass: HomeAssistant,
    mock_auth: MagicMock,
    mock_api: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A connection that cannot be deleted is named in the log."""
    mock_api.wait_for_admission.side_effect = TimeoutError()
    mock_api.delete_connection.side_effect = ThalovantConnectionError("down")
    result = await _pick_hub(hass, await _finish_login(hass, await _start(hass)))
    result = await _finish_admission(hass, result)
    assert result["errors"] == {"base": "admission_timeout"}
    assert (
        "Could not delete the unused connection Home Assistant (Maison)" in caplog.text
    )


async def test_admission_has_its_own_deadline(
    hass: HomeAssistant, mock_auth: MagicMock, mock_api: MagicMock
) -> None:
    """A library call that never returns still ends the wait."""
    never = asyncio.Event()

    async def hang(*_: Any, **__: Any) -> None:
        await never.wait()

    mock_api.wait_for_admission.side_effect = hang
    with (
        patch("custom_components.thalovant.config_flow.ADMISSION_TIMEOUT", 0),
        patch("custom_components.thalovant.config_flow.ADMISSION_GRACE", 0.01),
    ):
        result = await _pick_hub(hass, await _finish_login(hass, await _start(hass)))
        result = await _finish_admission(hass, result)
    assert result["errors"] == {"base": "admission_timeout"}


async def test_flow_closed_during_admission(
    hass: HomeAssistant, mock_auth: MagicMock, mock_api: MagicMock
) -> None:
    """Walking away while the hub admits us deletes the connection."""
    never = asyncio.Event()

    async def hang(*_: Any, **__: Any) -> None:
        await never.wait()

    mock_api.wait_for_admission.side_effect = hang
    result = await _pick_hub(hass, await _finish_login(hass, await _start(hass)))
    assert result["step_id"] == "admission"

    hass.config_entries.flow.async_abort(result["flow_id"])
    await hass.async_block_till_done(wait_background_tasks=True)
    mock_api.delete_connection.assert_awaited_once_with(CONNECTION_ID)
    mock_api.revoke_token.assert_awaited_once_with()
    # The connection needs the token to be deleted, so the token goes last.
    assert [name for name, *_ in mock_api.method_calls[-2:]] == [
        "delete_connection",
        "revoke_token",
    ]


async def _start_reauth(hass: HomeAssistant, entry: MockConfigEntry) -> dict[str, Any]:
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["description_placeholders"] == {"name": "Maison"}
    return await hass.config_entries.flow.async_configure(result["flow_id"], {})


async def test_reauth_closed_during_admission(
    hass: HomeAssistant,
    mock_auth: MagicMock,
    mock_api: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Closing reauth mid-admission deletes the new connection, keeps the entry's token."""
    never = asyncio.Event()

    async def hang(*_: Any, **__: Any) -> None:
        await never.wait()

    mock_api.wait_for_admission.side_effect = hang
    result = await _start_reauth(hass, mock_config_entry)
    assert result["step_id"] == "admission"
    mock_api.delete_connection.reset_mock()

    hass.config_entries.flow.async_abort(result["flow_id"])
    await hass.async_block_till_done(wait_background_tasks=True)
    mock_api.delete_connection.assert_awaited_once_with(CONNECTION_ID)
    mock_api.revoke_token.assert_not_awaited()


async def test_reauth_with_stored_token(
    hass: HomeAssistant,
    mock_auth: MagicMock,
    mock_api: MagicMock,
    mock_config_entry: MockConfigEntry,
    credentials: ConnectionCredentials,
) -> None:
    """A stored token that still works renews the link without a sign-in."""
    mock_api.create_connection.return_value = replace(
        credentials, connection_id="conn-new"
    )
    result = await _finish_admission(hass, await _start_reauth(hass, mock_config_entry))
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"

    mock_auth.start_device_login.assert_not_awaited()
    mock_api.delete_connection.assert_awaited_once_with(CONNECTION_ID)
    assert mock_config_entry.data[CONF_CREDENTIALS]["connection_id"] == "conn-new"
    assert mock_config_entry.unique_id == f"{ACCOUNT_ID}:{HUB_ID}"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_reauth_stored_token_rejected(
    hass: HomeAssistant,
    mock_auth: MagicMock,
    mock_api: MagicMock,
    mock_config_entry: MockConfigEntry,
    account: Account,
    tokens: Tokens,
) -> None:
    """A rejected stored token leads straight into a new sign-in."""
    new_tokens = replace(tokens, access_token="tvt_access_new")
    mock_auth.poll_device_login.return_value = new_tokens
    mock_api.get_account.side_effect = [ThalovantAuthError("revoked"), account]
    result = await _finish_login(hass, await _start_reauth(hass, mock_config_entry))
    result = await _finish_admission(hass, result)
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data[CONF_TOKENS] == new_tokens.to_dict()


async def test_reauth_without_stored_token(
    hass: HomeAssistant,
    mock_auth: MagicMock,
    mock_api: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """An entry whose tokens cannot be read signs in again."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        data={**mock_config_entry.data, CONF_TOKENS: {"broken": True}},
    )
    result = await _finish_login(hass, await _start_reauth(hass, mock_config_entry))
    result = await _finish_admission(hass, result)
    assert result["reason"] == "reauth_successful"
    mock_auth.start_device_login.assert_awaited_once()


async def test_reauth_old_connection_already_gone(
    hass: HomeAssistant,
    mock_auth: MagicMock,
    mock_api: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A connection deleted from the dashboard does not stop reauth."""
    mock_api.delete_connection.side_effect = ThalovantError("404", status=404)
    result = await _finish_admission(hass, await _start_reauth(hass, mock_config_entry))
    assert result["reason"] == "reauth_successful"


async def test_reauth_wrong_account(
    hass: HomeAssistant,
    mock_auth: MagicMock,
    mock_api: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Signing in to another account does not take over the link."""
    mock_api.get_account.return_value = Account(
        id="someone-else", display_name=None, email=None
    )
    result = await _start_reauth(hass, mock_config_entry)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"
    mock_api.create_connection.assert_not_awaited()
    # The stored token was the entry's, not minted here: it stays.
    await hass.async_block_till_done(wait_background_tasks=True)
    mock_api.revoke_token.assert_not_awaited()


async def test_reauth_new_sign_in_wrong_account(
    hass: HomeAssistant,
    mock_auth: MagicMock,
    mock_api: MagicMock,
    mock_config_entry: MockConfigEntry,
    account: Account,
) -> None:
    """A token minted for the wrong account is revoked when reauth aborts."""
    mock_api.get_account.side_effect = [
        ThalovantAuthError("revoked"),
        Account(id="someone-else", display_name=None, email=None),
    ]
    result = await _finish_login(hass, await _start_reauth(hass, mock_config_entry))
    assert result["reason"] == "wrong_account"
    await hass.async_block_till_done(wait_background_tasks=True)
    mock_api.revoke_token.assert_awaited_once_with()


async def test_reauth_hub_gone(
    hass: HomeAssistant,
    mock_auth: MagicMock,
    mock_api: MagicMock,
    mock_config_entry: MockConfigEntry,
    hubs: list[Hub],
) -> None:
    """A hub the account lost cannot be relinked."""
    mock_api.list_hubs.return_value = [hubs[1]]
    result = await _start_reauth(hass, mock_config_entry)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "hub_not_found"


async def test_reauth_errors_return_to_confirm(
    hass: HomeAssistant,
    mock_auth: MagicMock,
    mock_api: MagicMock,
    mock_config_entry: MockConfigEntry,
    account: Account,
) -> None:
    """Failures during reauth come back to its own first step."""
    mock_api.create_connection.side_effect = ThalovantConnectionError("503")
    result = await _start_reauth(hass, mock_config_entry)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": "cannot_connect"}

    mock_api.create_connection.side_effect = None
    mock_api.wait_for_admission.side_effect = TimeoutError()
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    result = await _finish_admission(hass, result)
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": "admission_timeout"}

    mock_api.wait_for_admission.side_effect = None
    mock_api.get_account.side_effect = [ThalovantAuthError("revoked"), account]
    mock_auth.start_device_login.side_effect = ThalovantConnectionError("dns")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": "cannot_connect"}

    mock_auth.start_device_login.side_effect = None
    mock_auth.poll_device_login.side_effect = DeviceLoginDenied()
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    result = await _finish_login(hass, result)
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": "login_denied"}


async def test_reauth_reloads_entry(
    hass: HomeAssistant,
    mock_auth: MagicMock,
    mock_api: MagicMock,
    mock_config_entry: MockConfigEntry,
    mock_setup_entry: AsyncMock,
) -> None:
    """A successful reauth reloads the entry."""
    result = await _finish_admission(hass, await _start_reauth(hass, mock_config_entry))
    assert result["reason"] == "reauth_successful"
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert len(mock_setup_entry.mock_calls) == 1


async def test_options_flow(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    issue_registry: ir.IssueRegistry,
) -> None:
    """The options pick the conversation agent, which settles its repair issue."""
    assert await async_setup_component(hass, "conversation", {})
    mock_config_entry.add_to_hass(hass)
    issue_id = agent_issue_id(mock_config_entry.entry_id)
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="agent_unavailable",
    )

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    schema_key = next(iter(result["data_schema"].schema))
    assert schema_key.default() == conversation.HOME_ASSISTANT_AGENT

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_AGENT_ID: "conversation.missing"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_AGENT_ID: "agent_not_found"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_AGENT_ID: conversation.HOME_ASSISTANT_AGENT}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options == {
        CONF_AGENT_ID: conversation.HOME_ASSISTANT_AGENT
    }
    assert issue_registry.async_get_issue(DOMAIN, issue_id) is None


async def test_first_step_links_the_guide(hass: HomeAssistant) -> None:
    """The first step points at the step-by-step guide."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["description_placeholders"] == {
        "guide_url": "https://docs.thalovant.com/manage/home-assistant/"
    }


@pytest.mark.parametrize(
    ("language", "not_ready"),
    [
        ("en", "Maison (can't link Home Assistant yet)"),
        ("fr", "Maison (ne peut pas encore être relié)"),
    ],
)
async def test_hubs_that_can_link_come_first(
    hass: HomeAssistant,
    mock_auth: MagicMock,
    mock_api: MagicMock,
    language: str,
    not_ready: str,
) -> None:
    """Linkable hubs first, unknown next, the ones that cannot last and marked."""
    hass.config.language = language
    mock_api.list_hubs.return_value = [
        Hub(HUB_ID, "Maison", can_link=False),
        Hub("unknown", "Atelier"),
        Hub(OTHER_HUB_ID, "Daily Desk", can_link=True),
    ]
    result = await _finish_login(hass, await _start(hass))
    options = result["data_schema"].schema[CONF_HUB_ID].config["options"]
    assert [option["label"] for option in options] == [
        "Daily Desk",
        "Atelier",
        not_ready,
    ]


async def test_hub_that_cannot_link_is_refused_before_anything_is_made(
    hass: HomeAssistant,
    mock_auth: MagicMock,
    mock_api: MagicMock,
) -> None:
    """Picking a hub the API says cannot link explains why and creates nothing."""
    mock_api.list_hubs.return_value = [
        Hub(HUB_ID, "Maison", can_link=False),
        Hub(OTHER_HUB_ID, "Daily Desk", can_link=True),
    ]
    result = await _pick_hub(hass, await _finish_login(hass, await _start(hass)))
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "hub"
    assert result["errors"] == {"base": "hub_cannot_link"}
    mock_api.create_connection.assert_not_awaited()

    # Another hub still works from the same form.
    result = await _pick_hub(hass, result, OTHER_HUB_ID)
    assert result["type"] is FlowResultType.SHOW_PROGRESS
    mock_api.create_connection.assert_awaited_once()


async def test_not_ready_label_without_translation(
    hass: HomeAssistant,
    mock_auth: MagicMock,
    mock_api: MagicMock,
) -> None:
    """A translation that lacks the label, or its placeholder, falls back to English."""
    mock_api.list_hubs.return_value = [Hub(HUB_ID, "Maison", can_link=False)]
    with patch(
        "custom_components.thalovant.config_flow.translation.async_get_translations",
        AsyncMock(return_value={"component.thalovant.common.hub_not_ready": "?"}),
    ):
        result = await _finish_login(hass, await _start(hass))
    options = result["data_schema"].schema[CONF_HUB_ID].config["options"]
    assert [option["label"] for option in options] == [
        "Maison (can't link Home Assistant yet)"
    ]
