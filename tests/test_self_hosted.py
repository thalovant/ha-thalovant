"""Private Christmas link config, lifecycle, and Assist scope regressions."""

from dataclasses import replace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.thalovant.api import (
    HubConnection,
    HubMessage,
    ThalovantConnectionError,
)
from custom_components.thalovant.const import (
    CONF_AGENT_ID,
    CONF_CREDENTIALS,
    CONF_HOME_CLIENT_ID,
    CONF_HUB_ID,
    CONF_HUB_NAME,
    CONF_SELF_HOSTED,
    CONF_TOKENS,
    CONF_VOICE_CLIENT_ID,
    DOMAIN,
    REQUEST_MESSAGE_TYPE,
    RESPONSE_MESSAGE_TYPE,
)
from custom_components.thalovant.diagnostics import async_get_config_entry_diagnostics
from custom_components.thalovant.self_hosted import (
    connection_client_ids,
    connection_secret,
    credentials_for,
    normalize_endpoint,
    permits_lighting_request,
    validate_credentials,
)
from homeassistant.components import conversation
from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_USER, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import intent
from homeassistant.setup import async_setup_component

from .conftest import FakeHubConnection

ENDPOINT = "wss://private-hub.example.com"
ACCESS_KEY = "private-access-key-test"
PASSWORD = "private-password-test"
HOME_ID = "8"
VOICE_ID = "3"
REQUEST_ID = "01" * 16
LEASE = "0123456789abcdef"


def _form(**changes: str) -> dict[str, str]:
    return {
        "endpoint": ENDPOINT,
        CONF_HOME_CLIENT_ID: HOME_ID,
        CONF_VOICE_CLIENT_ID: VOICE_ID,
        "access_key": ACCESS_KEY,
        "password": PASSWORD,
        **changes,
    }


def _entry_data() -> dict[str, Any]:
    creds = credentials_for(ENDPOINT, HOME_ID, ACCESS_KEY, PASSWORD)
    return {
        CONF_HUB_ID: creds.hub_id,
        CONF_HUB_NAME: creds.name,
        CONF_SELF_HOSTED: True,
        CONF_HOME_CLIENT_ID: HOME_ID,
        CONF_VOICE_CLIENT_ID: VOICE_ID,
        CONF_CREDENTIALS: creds.to_dict(),
    }


def _message(action: str = "begin") -> HubMessage:
    return HubMessage(
        type=REQUEST_MESSAGE_TYPE,
        data={
            "request_id": REQUEST_ID,
            "utterance": f"thalovant christmas mirror {action} {LEASE}",
            "lang": "en-US",
            "device": {"id": VOICE_ID, "name": "Operator-registered Voice"},
        },
        context={
            "source": "thalovant.home.router",
            "destination": "ha-thalovant-8::node",
            "session": {"session_id": f"home-{REQUEST_ID}", "lang": "en-US"},
        },
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("WSS://Private-Hub.example.com:443/", ENDPOINT),
        ("wss://private-hub.example.com:9443/", ENDPOINT + ":9443"),
    ],
)
def test_endpoint_canonicalization(value: str, expected: str) -> None:
    assert normalize_endpoint(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        None,
        "wss://" + "a" * 271,
        "wss://" + ".".join(["a" * 63] * 4 + ["ab"]),
        "ws://private-hub.example.com",
        "wss://private-hub.example.com:65536",
        "wss://user:pass@private-hub.example.com",
        "wss://private-hub.example.com?access_key=fake",
        "wss://private-hub.example.com#fake",
        "wss://private-hub.example.com/another-path",
        "wss://private-hub.example.com/%2F",
        "wss://private-hub.example.com\n",
        "wss://private-hub.example.com\\@redirect.example.com",
    ],
)
def test_endpoint_refuses_alternates(value: object) -> None:
    with pytest.raises(ValueError, match="Invalid WebSocket endpoint"):
        normalize_endpoint(value)


@pytest.mark.parametrize("value", [None, 1, "0", "03", "3 ", "3\n", "3" * 20])
def test_client_id_validation(value: object) -> None:
    with pytest.raises(ValueError, match="Invalid client ID"):
        connection_client_ids(
            {CONF_HOME_CLIENT_ID: HOME_ID, CONF_VOICE_CLIENT_ID: value}
        )


def test_client_id_must_be_distinct() -> None:
    with pytest.raises(ValueError, match="must be separate"):
        connection_client_ids(_form(voice_client_id=HOME_ID))


@pytest.mark.parametrize("value", [None, "", "a\nb", "a b", "a" * 257])
def test_operator_secret_validation(value: object) -> None:
    with pytest.raises(ValueError, match="Invalid connection credential"):
        connection_secret(value)


def test_identity_is_namespaced_and_refuses_persisted_endpoint_override() -> None:
    credentials = credentials_for(ENDPOINT, HOME_ID, ACCESS_KEY, PASSWORD)
    other = credentials_for("wss://other.example.com", HOME_ID, ACCESS_KEY, PASSWORD)
    assert credentials.connection_id != other.connection_id
    assert credentials.hub_id != other.hub_id
    assert ACCESS_KEY not in repr(credentials)
    assert PASSWORD not in repr(credentials)
    validate_credentials(credentials, _entry_data())
    with pytest.raises(ValueError, match="Invalid private hub identity"):
        validate_credentials(other, _entry_data())
    with pytest.raises(ValueError, match="Invalid private hub identity"):
        validate_credentials(
            replace(
                credentials, secret={**credentials.secret, "host": "other.example.com"}
            ),
            _entry_data(),
        )


def test_sdk_constructor_refuses_a_different_inner_endpoint() -> None:
    credentials = credentials_for(ENDPOINT, HOME_ID, ACCESS_KEY, PASSWORD)
    with pytest.raises(ValueError, match="does not match its endpoint"):
        HubConnection(
            MagicMock(),
            replace(credentials, endpoint="wss://other.example.com"),
            self_hosted=True,
        )


@pytest.mark.parametrize(
    "action", ["begin", "candle", "cranberry", "evergreen", "photo", "finale", "end"]
)
def test_all_bounded_lighting_actions_are_admitted(action: str) -> None:
    assert permits_lighting_request(_message(action), VOICE_ID)


@pytest.mark.parametrize(
    ("data_override", "context_override", "kind", "allowed"),
    [
        ({}, {}, RESPONSE_MESSAGE_TYPE, VOICE_ID),
        ({}, {}, REQUEST_MESSAGE_TYPE, None),
        ({}, {}, REQUEST_MESSAGE_TYPE, "03"),
        ({}, {"source": "untrusted::client"}, REQUEST_MESSAGE_TYPE, VOICE_ID),
        ({}, {"session": "default"}, REQUEST_MESSAGE_TYPE, VOICE_ID),
        (
            {},
            {"session": {"session_id": "wrong", "lang": "en-US"}},
            REQUEST_MESSAGE_TYPE,
            VOICE_ID,
        ),
        (
            {},
            {"session": {"session_id": f"home-{REQUEST_ID}", "lang": "fr"}},
            REQUEST_MESSAGE_TYPE,
            VOICE_ID,
        ),
        ({"device": "name-only"}, {}, REQUEST_MESSAGE_TYPE, VOICE_ID),
        (
            {"device": {"id": "2", "name": "Operator-registered Voice"}},
            {},
            REQUEST_MESSAGE_TYPE,
            VOICE_ID,
        ),
        ({"request_id": None}, {}, REQUEST_MESSAGE_TYPE, VOICE_ID),
        ({"request_id": "bad-id"}, {}, REQUEST_MESSAGE_TYPE, VOICE_ID),
        ({"lang": "fr"}, {}, REQUEST_MESSAGE_TYPE, VOICE_ID),
        (
            {"conversation_id": "continue-a-different-command"},
            {},
            REQUEST_MESSAGE_TYPE,
            VOICE_ID,
        ),
        (
            {"utterance": "turn off the kitchen light"},
            {},
            REQUEST_MESSAGE_TYPE,
            VOICE_ID,
        ),
        (
            {"utterance": f"thalovant christmas mirror end {LEASE}\n"},
            {},
            REQUEST_MESSAGE_TYPE,
            VOICE_ID,
        ),
        ({"utterance": None}, {}, REQUEST_MESSAGE_TYPE, VOICE_ID),
    ],
)
def test_scope_rejects_other_messages(
    data_override: dict[str, Any],
    context_override: dict[str, Any],
    kind: str,
    allowed: str | None,
) -> None:
    message = _message()
    changed = replace(
        message,
        type=kind,
        data={**message.data, **data_override},
        context={**message.context, **context_override},
    )
    assert not permits_lighting_request(changed, allowed)


async def _open_private_flow(hass: HomeAssistant) -> str:
    first = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert first["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(
        first["flow_id"], {CONF_SELF_HOSTED: True}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "self_hosted"
    assert result["data_schema"].schema["access_key"].config["type"] == "password"
    assert result["data_schema"].schema["password"].config["type"] == "password"
    return result["flow_id"]


async def test_private_pairing_does_not_create_cloud_credentials(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    mock_api: MagicMock,
    mock_auth: MagicMock,
) -> None:
    flow_id = await _open_private_flow(hass)
    rejected = await hass.config_entries.flow.async_configure(
        flow_id, _form(endpoint="ws://private-hub.example.com")
    )
    assert rejected["errors"] == {"base": "invalid_private_link"}
    result = await hass.config_entries.flow.async_configure(flow_id, _form())
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == _entry_data()
    assert CONF_TOKENS not in result["data"]
    mock_setup_entry.assert_awaited_once()
    mock_auth.start_device_login.assert_not_awaited()
    mock_api.create_connection.assert_not_awaited()

    duplicate_flow = await _open_private_flow(hass)
    duplicate = await hass.config_entries.flow.async_configure(
        duplicate_flow, _form(endpoint=ENDPOINT + ":443/")
    )
    assert duplicate["type"] is FlowResultType.ABORT
    assert duplicate["reason"] == "already_configured"


@pytest.fixture
def private_entry(hass: HomeAssistant) -> MockConfigEntry:
    data = _entry_data()
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=data[CONF_HUB_ID],
        title=data[CONF_HUB_NAME],
        data=data,
        options={CONF_AGENT_ID: "conversation.untrusted_agent"},
    )
    entry.add_to_hass(hass)
    return entry


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"endpoint": "wss://different.example.com"}, "different_private_hub"),
        ({CONF_VOICE_CLIENT_ID: "4"}, "different_private_hub"),
        (
            {CONF_HOME_CLIENT_ID: "9", "password": "replacement-password"},
            "reauth_successful",
        ),
    ],
)
async def test_private_reauth_preserves_endpoint_and_scope(
    hass: HomeAssistant,
    private_entry: MockConfigEntry,
    mock_setup_entry: AsyncMock,
    mock_auth: MagicMock,
    changes: dict[str, str],
    reason: str,
) -> None:
    first = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_REAUTH, "entry_id": private_entry.entry_id},
        data=private_entry.data,
    )
    assert first["step_id"] == "self_hosted"
    result = await hass.config_entries.flow.async_configure(
        first["flow_id"], _form(**changes)
    )
    assert result["reason"] == reason
    assert private_entry.data[CONF_VOICE_CLIENT_ID] == VOICE_ID
    if reason == "reauth_successful":
        assert private_entry.data[CONF_HOME_CLIENT_ID] == "9"
        assert (
            private_entry.data[CONF_CREDENTIALS]["secret"]["password"]
            == "replacement-password"
        )
    else:
        assert private_entry.data[CONF_HOME_CLIENT_ID] == HOME_ID
    mock_auth.start_device_login.assert_not_awaited()


async def test_private_options_keep_builtin_assist(
    hass: HomeAssistant, private_entry: MockConfigEntry
) -> None:
    result = await hass.config_entries.options.async_init(private_entry.entry_id)
    assert result["reason"] == "private_agent_fixed"


async def test_private_handler_rejects_unapproved_speakers_before_assist(
    hass: HomeAssistant,
    private_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
) -> None:
    assert await async_setup_component(hass, "conversation", {})
    assert await hass.config_entries.async_setup(private_entry.entry_id)
    message = _message("finale")
    result = intent.IntentResponse(language="en")
    result.response_type = intent.IntentResponseType.ACTION_DONE
    result.async_set_speech(f"thalovant-mirror-ok finale {LEASE}")

    with patch(
        "custom_components.thalovant.handler.conversation.async_converse",
        new=AsyncMock(return_value=conversation.ConversationResult(result)),
    ) as converse:
        await mock_hub_connection.emit(
            REQUEST_MESSAGE_TYPE,
            {
                **message.data,
                "device": {"id": "2", "name": "Operator-registered Voice"},
            },
            message.context,
        )
        await hass.async_block_till_done(wait_background_tasks=False)
        converse.assert_not_called()
        mock_hub_connection.reply.assert_not_awaited()

        await mock_hub_connection.emit(
            REQUEST_MESSAGE_TYPE, message.data, message.context
        )
        response = await mock_hub_connection.next_reply()
        assert response["speech"] == f"thalovant-mirror-ok finale {LEASE}"
        assert (
            converse.await_args.kwargs["agent_id"] == conversation.HOME_ASSISTANT_AGENT
        )
        assert converse.await_args.kwargs["text"] == message.data["utterance"]


async def test_private_setup_and_removal_are_local_only(
    hass: HomeAssistant,
    private_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_api: MagicMock,
) -> None:
    assert await hass.config_entries.async_setup(private_entry.entry_id)
    assert private_entry.state is ConfigEntryState.LOADED
    (session, _) = mock_hub_connection.factory.call_args.args
    assert not session.closed
    arguments = mock_hub_connection.factory.call_args.kwargs
    assert arguments["self_hosted"] is True
    assert "self_hosted_" in arguments["state_dir"]
    diagnostics = await async_get_config_entry_diagnostics(hass, private_entry)
    assert diagnostics["connection"]["endpoint"] == "**REDACTED**"
    assert diagnostics["entry"]["data"][CONF_CREDENTIALS] == "**REDACTED**"
    assert diagnostics["entry"]["data"][CONF_VOICE_CLIENT_ID] == "**REDACTED**"
    assert ACCESS_KEY not in repr(diagnostics)
    assert PASSWORD not in repr(diagnostics)
    await hass.config_entries.async_remove(private_entry.entry_id)
    assert session.closed
    mock_hub_connection.close.assert_awaited_once()
    mock_api.delete_connection.assert_not_awaited()
    mock_api.revoke_token.assert_not_awaited()


async def test_private_setup_retry_releases_its_http_session(
    hass: HomeAssistant,
    private_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
) -> None:
    mock_hub_connection.connect.side_effect = ThalovantConnectionError("refused")
    await hass.config_entries.async_setup(private_entry.entry_id)

    assert private_entry.state is ConfigEntryState.SETUP_RETRY
    (session, _) = mock_hub_connection.factory.call_args.args
    assert session.closed
    mock_hub_connection.close.assert_awaited_once()
