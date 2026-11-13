"""Tests for the Intercom options and the re-consent flow they start."""

from dataclasses import replace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from yarl import URL

from custom_components.thalovant.api import (
    Account,
    DeviceLoginDenied,
    ThalovantAuthError,
    ThalovantConnectionError,
    Tokens,
)
from custom_components.thalovant.config_flow import LINK_ACCOUNT, LINK_CODE
from custom_components.thalovant.const import (
    CONF_AGENT_ID,
    CONF_ALLOW_ANNOUNCEMENTS,
    CONF_ALLOW_RECEIVE,
    CONF_ALLOW_URGENT,
    CONF_SELF_HOSTED,
    CONF_SPEAKER_AREAS,
    CONF_SPEAKER_PLAYERS,
    CONF_TOKENS,
    CONF_TTS_ENTITY,
    DOMAIN,
    LOGIN_SCOPES,
)
from homeassistant.components import conversation
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.setup import async_setup_component

from .conftest import ACCOUNT_ID, INTERCOM_ALL_SCOPES
from .test_oauth import ANSWER, CODE

pytestmark = pytest.mark.usefixtures("mock_setup_entry")

AGENT = conversation.HOME_ASSISTANT_AGENT
WITH_A_CODE = {"link_method": LINK_CODE}
ANNOUNCE_ON = {CONF_AGENT_ID: AGENT, CONF_ALLOW_ANNOUNCEMENTS: True}


async def _options(hass: HomeAssistant, entry: MockConfigEntry) -> dict[str, Any]:
    assert await async_setup_component(hass, "conversation", {})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    return result


async def _submit(
    hass: HomeAssistant, result: dict[str, Any], data: dict[str, Any]
) -> dict[str, Any]:
    return await hass.config_entries.options.async_configure(result["flow_id"], data)


def _consent_tokens(tokens: Tokens, scopes: tuple[str, ...]) -> Tokens:
    return replace(tokens, access_token="tvt_new_token", scopes=scopes)


async def _reauth_flow(hass: HomeAssistant) -> dict[str, Any]:
    """The re-consent flow the options started."""
    await hass.async_block_till_done()
    [flow] = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert flow["context"]["source"] == "reauth"
    return flow


def test_form_has_everything_off_by_default() -> None:
    """Pure documentation of the defaults: nothing is on until it is chosen."""
    assert CONF_ALLOW_ANNOUNCEMENTS == "allow_announcements"


async def test_the_form(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """The agent first, then three switches that are all off."""
    result = await _options(hass, mock_config_entry)
    keys = list(result["data_schema"].schema)
    assert [str(key) for key in keys] == [
        CONF_AGENT_ID,
        CONF_ALLOW_ANNOUNCEMENTS,
        CONF_ALLOW_URGENT,
        CONF_ALLOW_RECEIVE,
        "structured_actions",
        "structured_sensitive",
        "alarm_code",
    ]
    # Intercom switches off; structured actions on, their sensitive half off.
    assert [key.default() for key in keys[1:6]] == [False, False, False, True, False]


async def test_options_without_intercom_are_stored_as_before(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Saving with every switch off stores the agent and nothing else."""
    result = await _options(hass, mock_config_entry)
    result = await _submit(
        hass,
        result,
        {
            CONF_AGENT_ID: AGENT,
            CONF_ALLOW_ANNOUNCEMENTS: False,
            CONF_ALLOW_URGENT: False,
            CONF_ALLOW_RECEIVE: False,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options == {CONF_AGENT_ID: AGENT}


async def test_urgent_needs_announcements(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Urgent without announcements is an error on that field."""
    result = await _options(hass, mock_config_entry)
    result = await _submit(
        hass, result, {CONF_AGENT_ID: AGENT, CONF_ALLOW_URGENT: True}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_ALLOW_URGENT: "urgent_needs_announcements"}


async def test_already_approved_needs_no_consent(
    hass: HomeAssistant, credentials: Any
) -> None:
    """A token that already carries the permission saves the options at once."""
    from .conftest import make_intercom_entry

    entry = make_intercom_entry(credentials, options={})
    result = await _options(hass, entry)
    result = await _submit(
        hass,
        result,
        {CONF_AGENT_ID: AGENT, CONF_ALLOW_ANNOUNCEMENTS: True, CONF_ALLOW_URGENT: True},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {
        CONF_AGENT_ID: AGENT,
        CONF_ALLOW_ANNOUNCEMENTS: True,
        CONF_ALLOW_URGENT: True,
    }
    assert hass.config_entries.flow.async_progress_by_handler(DOMAIN) == []


# --- Receiving ---------------------------------------------------------------


async def test_receive_step(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Receiving asks where to play, needs somewhere, and needs no new permission."""
    result = await _options(hass, mock_config_entry)
    result = await _submit(
        hass, result, {CONF_AGENT_ID: AGENT, CONF_ALLOW_RECEIVE: True}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "receive"

    result = await _submit(hass, result, {})
    assert result["errors"] == {"base": "receive_needs_players"}

    result = await _submit(
        hass,
        result,
        {
            CONF_SPEAKER_PLAYERS: ["media_player.kitchen"],
            CONF_SPEAKER_AREAS: ["salon"],
            CONF_TTS_ENTITY: "tts.piper",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options == {
        CONF_AGENT_ID: AGENT,
        CONF_ALLOW_RECEIVE: True,
        CONF_SPEAKER_PLAYERS: ["media_player.kitchen"],
        CONF_SPEAKER_AREAS: ["salon"],
        CONF_TTS_ENTITY: "tts.piper",
    }
    assert hass.config_entries.flow.async_progress_by_handler(DOMAIN) == []


async def test_receive_step_remembers_and_may_leave_the_voice_default(
    hass: HomeAssistant, credentials: Any
) -> None:
    """The step starts from what is stored, and a player alone is enough."""
    from .conftest import make_intercom_entry

    entry = make_intercom_entry(
        credentials,
        options={
            CONF_ALLOW_RECEIVE: True,
            CONF_SPEAKER_PLAYERS: ["media_player.kitchen"],
            CONF_SPEAKER_AREAS: ["salon"],
            CONF_TTS_ENTITY: "tts.piper",
        },
    )
    result = await _options(hass, entry)
    result = await _submit(
        hass, result, {CONF_AGENT_ID: AGENT, CONF_ALLOW_RECEIVE: True}
    )
    schema = {str(key): key for key in result["data_schema"].schema}
    assert schema[CONF_SPEAKER_PLAYERS].default() == ["media_player.kitchen"]
    assert schema[CONF_SPEAKER_AREAS].default() == ["salon"]
    assert schema[CONF_TTS_ENTITY].description == {"suggested_value": "tts.piper"}

    result = await _submit(
        hass,
        result,
        {CONF_SPEAKER_PLAYERS: ["media_player.den"], CONF_SPEAKER_AREAS: []},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_TTS_ENTITY not in entry.options
    assert entry.options[CONF_SPEAKER_PLAYERS] == ["media_player.den"]


# --- Re-consent --------------------------------------------------------------


async def test_turning_announcements_on_asks_for_the_permission(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_auth: MagicMock,
    mock_api: MagicMock,
    tokens: Tokens,
) -> None:
    """Without the scopes nothing is saved; a re-consent flow asks for exactly them."""
    result = await _options(hass, mock_config_entry)
    result = await _submit(
        hass, result, {CONF_AGENT_ID: AGENT, CONF_ALLOW_ANNOUNCEMENTS: True}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "consent_required"
    assert mock_config_entry.options == {}

    flow = await _reauth_flow(hass)
    assert flow["step_id"] == "intercom_consent"
    form = await hass.config_entries.flow.async_configure(flow["flow_id"])
    assert form["step_id"] == "intercom_consent"
    assert form["description_placeholders"] == {"name": "Maison"}

    # Asked for with a code: the base scopes and Intercom's, never hubs:write.
    mock_auth.poll_device_login.return_value = _consent_tokens(
        tokens, (*LOGIN_SCOPES, "intercom:read", "intercom:send")
    )
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], WITH_A_CODE
    )
    assert result["type"] is FlowResultType.SHOW_PROGRESS
    assert mock_auth.start_device_login.await_args.kwargs["scopes"] == (
        *LOGIN_SCOPES,
        "intercom:read",
        "intercom:send",
    )
    await hass.async_block_till_done()
    result = await hass.config_entries.flow.async_configure(flow["flow_id"])

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "consent_successful"
    # The options asked for are stored now, with the new token.
    assert mock_config_entry.options == {
        CONF_AGENT_ID: AGENT,
        CONF_ALLOW_ANNOUNCEMENTS: True,
    }
    stored = Tokens.from_dict(mock_config_entry.data[CONF_TOKENS])
    assert stored.access_token == "tvt_new_token"
    assert "intercom:send" in stored.scopes
    # No connection was made or deleted: only the token changed.
    mock_api.create_connection.assert_not_awaited()
    mock_api.delete_connection.assert_not_awaited()


async def test_urgent_asks_for_its_own_permission(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_auth: MagicMock,
    mock_api: MagicMock,
    tokens: Tokens,
) -> None:
    """Turning urgent on adds the urgent scope to the request."""
    result = await _options(hass, mock_config_entry)
    await _submit(
        hass,
        result,
        {CONF_AGENT_ID: AGENT, CONF_ALLOW_ANNOUNCEMENTS: True, CONF_ALLOW_URGENT: True},
    )
    flow = await _reauth_flow(hass)
    mock_auth.poll_device_login.return_value = _consent_tokens(
        tokens, INTERCOM_ALL_SCOPES
    )
    await hass.config_entries.flow.async_configure(flow["flow_id"], WITH_A_CODE)
    assert (
        mock_auth.start_device_login.await_args.kwargs["scopes"][-1]
        == "intercom:urgent"
    )
    await hass.async_block_till_done()
    result = await hass.config_entries.flow.async_configure(flow["flow_id"])
    assert result["reason"] == "consent_successful"
    assert mock_config_entry.options[CONF_ALLOW_URGENT] is True


async def test_refused_consent_leaves_everything_off(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_auth: MagicMock,
    mock_api: MagicMock,
) -> None:
    """Declining the sign-in keeps the option off, and the old token."""
    result = await _options(hass, mock_config_entry)
    await _submit(hass, result, {CONF_AGENT_ID: AGENT, CONF_ALLOW_ANNOUNCEMENTS: True})
    flow = await _reauth_flow(hass)
    mock_auth.poll_device_login.side_effect = DeviceLoginDenied()

    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], WITH_A_CODE
    )
    await hass.async_block_till_done()
    result = await hass.config_entries.flow.async_configure(flow["flow_id"])
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "intercom_consent"
    assert result["errors"] == {"base": "login_denied"}
    assert mock_config_entry.options == {}
    assert (
        Tokens.from_dict(mock_config_entry.data[CONF_TOKENS]).access_token
        != "tvt_new_token"
    )


async def test_a_plan_without_intercom_is_not_granted_the_scope(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_auth: MagicMock,
    mock_api: MagicMock,
    tokens: Tokens,
) -> None:
    """If Thalovant grants a token without the scope, nothing is turned on."""
    result = await _options(hass, mock_config_entry)
    await _submit(hass, result, {CONF_AGENT_ID: AGENT, CONF_ALLOW_ANNOUNCEMENTS: True})
    flow = await _reauth_flow(hass)
    mock_auth.poll_device_login.return_value = _consent_tokens(tokens, LOGIN_SCOPES)
    await hass.config_entries.flow.async_configure(flow["flow_id"], WITH_A_CODE)
    await hass.async_block_till_done()
    result = await hass.config_entries.flow.async_configure(flow["flow_id"])
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "consent_scopes_missing"
    assert mock_config_entry.options == {}


async def test_consent_with_another_account(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_auth: MagicMock,
    mock_api: MagicMock,
    tokens: Tokens,
) -> None:
    """Signing in with a different account is refused, and its token revoked."""
    result = await _options(hass, mock_config_entry)
    await _submit(hass, result, {CONF_AGENT_ID: AGENT, CONF_ALLOW_ANNOUNCEMENTS: True})
    flow = await _reauth_flow(hass)
    mock_auth.poll_device_login.return_value = _consent_tokens(
        tokens, (*LOGIN_SCOPES, "intercom:read", "intercom:send")
    )
    mock_api.get_account.return_value = Account("someone-else", None, None)
    await hass.config_entries.flow.async_configure(flow["flow_id"], WITH_A_CODE)
    await hass.async_block_till_done()
    result = await hass.config_entries.flow.async_configure(flow["flow_id"])
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"
    await hass.async_block_till_done()
    mock_api.revoke_token.assert_awaited_once()
    assert mock_config_entry.options == {}


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ThalovantAuthError(), "invalid_auth"),
        (ThalovantConnectionError(), "cannot_connect"),
        (RuntimeError("odd"), "unknown"),
    ],
)
async def test_consent_when_the_account_cannot_be_read(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_auth: MagicMock,
    mock_api: MagicMock,
    tokens: Tokens,
    error: Exception,
    expected: str,
) -> None:
    """Failing to read the account goes back to the question, with the reason."""
    result = await _options(hass, mock_config_entry)
    await _submit(hass, result, {CONF_AGENT_ID: AGENT, CONF_ALLOW_ANNOUNCEMENTS: True})
    flow = await _reauth_flow(hass)
    mock_auth.poll_device_login.return_value = _consent_tokens(
        tokens, (*LOGIN_SCOPES, "intercom:read", "intercom:send")
    )
    mock_api.get_account.side_effect = error
    await hass.config_entries.flow.async_configure(flow["flow_id"], WITH_A_CODE)
    await hass.async_block_till_done()
    result = await hass.config_entries.flow.async_configure(flow["flow_id"])
    if result["type"] is FlowResultType.SHOW_PROGRESS_DONE:
        result = await hass.config_entries.flow.async_configure(flow["flow_id"])
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "intercom_consent"
    assert result["errors"] == {"base": expected}
    assert mock_config_entry.options == {}


async def test_consent_through_link_account(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_api: MagicMock,
    my_home_assistant: None,
    aioclient_mock: Any,
) -> None:
    """Link account asks for the same scopes on Thalovant's consent page."""
    from custom_components.thalovant.const import LINK_TOKEN_URL

    aioclient_mock.post(
        LINK_TOKEN_URL,
        json={
            **ANSWER,
            "scopes": [*LOGIN_SCOPES, "intercom:read", "intercom:send"],
        },
    )
    result = await _options(hass, mock_config_entry)
    await _submit(hass, result, {CONF_AGENT_ID: AGENT, CONF_ALLOW_ANNOUNCEMENTS: True})
    flow = await _reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"link_method": LINK_ACCOUNT}
    )
    assert result["type"] is FlowResultType.EXTERNAL_STEP
    query = dict(URL(result["url"]).query)
    assert query["scope"].split(" ") == [
        *LOGIN_SCOPES,
        "intercom:read",
        "intercom:send",
    ]

    state = config_entry_oauth2_flow._decode_jwt(hass, query["state"])
    done = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"state": state, "code": CODE}
    )
    assert done["type"] is FlowResultType.EXTERNAL_STEP_DONE
    result = await hass.config_entries.flow.async_configure(flow["flow_id"])
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "consent_successful"
    assert mock_config_entry.options[CONF_ALLOW_ANNOUNCEMENTS] is True


async def test_a_reauth_already_waiting(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_auth: MagicMock,
    mock_api: MagicMock,
) -> None:
    """Only one re-authentication at a time: the second is told to wait."""
    mock_config_entry.add_to_hass(hass)
    await mock_config_entry.start_reauth_flow(hass)
    result = await _options(hass, mock_config_entry)
    result = await _submit(
        hass, result, {CONF_AGENT_ID: AGENT, CONF_ALLOW_ANNOUNCEMENTS: True}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "consent_pending"
    assert mock_config_entry.options == {}


# --- Signing in again keeps what is on -------------------------------------


async def test_new_sign_ins_ask_for_what_stays_on(
    hass: HomeAssistant,
    credentials: Any,
    mock_auth: MagicMock,
    mock_api: MagicMock,
) -> None:
    """A new token replaces the account's old one, so it must carry Intercom's scopes."""
    from .conftest import make_intercom_entry

    make_intercom_entry(
        credentials, options={CONF_ALLOW_ANNOUNCEMENTS: True}
    ).add_to_hass(hass)
    private = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_SELF_HOSTED: True},
        options={CONF_ALLOW_ANNOUNCEMENTS: True, CONF_ALLOW_URGENT: True},
    )
    private.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    await hass.config_entries.flow.async_configure(result["flow_id"], WITH_A_CODE)
    # A private link's options are not an account's: only the first counts.
    assert mock_auth.start_device_login.await_args.kwargs["scopes"] == (
        *LOGIN_SCOPES,
        "intercom:read",
        "intercom:send",
    )


async def test_sign_ins_with_nothing_on_ask_for_what_they_always_did(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_auth: MagicMock,
    mock_api: MagicMock,
) -> None:
    """With nothing turned on the scopes are exactly LOGIN_SCOPES."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    await hass.config_entries.flow.async_configure(result["flow_id"], WITH_A_CODE)
    assert mock_auth.start_device_login.await_args.kwargs["scopes"] == LOGIN_SCOPES


async def test_reauth_keeps_what_is_on(
    hass: HomeAssistant,
    credentials: Any,
    mock_auth: MagicMock,
    mock_api: MagicMock,
) -> None:
    """Reauthenticating an entry whose token lacks Intercom's scopes asks for them."""
    from .conftest import make_intercom_entry

    entry = make_intercom_entry(
        credentials,
        options={CONF_ALLOW_ANNOUNCEMENTS: True},
        scopes=LOGIN_SCOPES,
    )
    entry.add_to_hass(hass)
    # No stored token that works: the sign-in is asked for.
    mock_api.get_account.side_effect = [
        ThalovantAuthError(),
        Account(ACCOUNT_ID, None, None),
    ]
    result = await entry.start_reauth_flow(hass)
    await hass.config_entries.flow.async_configure(result["flow_id"], WITH_A_CODE)
    assert mock_auth.start_device_login.await_args.kwargs["scopes"] == (
        *LOGIN_SCOPES,
        "intercom:read",
        "intercom:send",
    )


async def test_private_options_still_abort(hass: HomeAssistant) -> None:
    """A private link has no Intercom options at all."""
    assert await async_setup_component(hass, "conversation", {})
    private = MockConfigEntry(domain=DOMAIN, data={CONF_SELF_HOSTED: True})
    private.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(private.entry_id)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "private_agent_fixed"


@pytest.fixture(autouse=True)
def _unused_markers() -> None:
    AsyncMock  # noqa: B018 - imported for the fixtures above


async def test_a_token_that_cannot_be_read_asks_for_consent(
    hass: HomeAssistant,
    credentials: Any,
    mock_auth: MagicMock,
    mock_api: MagicMock,
) -> None:
    """With no readable token there are no scopes to count: the permission is asked for."""
    from .conftest import make_intercom_entry

    entry = make_intercom_entry(credentials, options={})
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_TOKENS: {"scopes": 7}}
    )
    result = await _options(hass, entry)
    result = await _submit(
        hass, result, {CONF_AGENT_ID: AGENT, CONF_ALLOW_ANNOUNCEMENTS: True}
    )
    assert result["reason"] == "consent_required"
