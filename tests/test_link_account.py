"""Link account in the config flow: the browser approval, then the same flow as a code.

The callback that My Home Assistant brings back is fed to the flow the way
Home Assistant's OAuth2AuthorizeCallbackView does (one test goes through the
view itself), and the token endpoint is Home Assistant's client mock.
"""

from dataclasses import replace
from typing import Any
from unittest.mock import MagicMock, patch

import aiohttp
from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)
from yarl import URL

from custom_components.thalovant.api import (
    Account,
    ConnectionCredentials,
    ThalovantAuthError,
    ThalovantConnectionError,
    Tokens,
)
from custom_components.thalovant.config_flow import (
    LINK_ACCOUNT,
    LINK_CODE,
    ThalovantConfigFlow,
)
from custom_components.thalovant.const import (
    CONF_ACCOUNT_ID,
    CONF_CREDENTIALS,
    CONF_HUB_ID,
    CONF_HUB_NAME,
    CONF_LINKED_AT,
    CONF_SELF_HOSTED,
    CONF_TOKENS,
    DOMAIN,
    LINK_TOKEN_URL,
)
from custom_components.thalovant.oauth import tokens_from_answer
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, UnknownFlow
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.config_entry_oauth2_flow import (
    MY_AUTH_CALLBACK_PATH,
    OAuth2AuthorizeCallbackView,
)
from homeassistant.helpers.selector import SelectSelector

from .conftest import ACCOUNT_ID, CONNECTION_ID, HUB_ID
from .test_oauth import ANSWER, CODE, _challenge

pytestmark = pytest.mark.usefixtures("mock_setup_entry")

LINKED = tokens_from_answer(ANSWER)


@pytest.fixture
def token_endpoint(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    """Thalovant's token endpoint, answering with a token."""
    aioclient_mock.post(LINK_TOKEN_URL, json=ANSWER)
    return aioclient_mock


def _query(result: dict[str, Any]) -> dict[str, str]:
    assert result["type"] is FlowResultType.EXTERNAL_STEP, result
    assert result["step_id"] == "auth"
    return dict(URL(result["url"]).query)


def _state(hass: HomeAssistant, result: dict[str, Any]) -> dict[str, Any]:
    state = config_entry_oauth2_flow._decode_jwt(hass, _query(result)["state"])
    assert state is not None
    return state


async def _come_back(
    hass: HomeAssistant, result: dict[str, Any], **query: str
) -> dict[str, Any]:
    """Bring the browser back as the callback view does, then let the flow go on."""
    callback = {"state": _state(hass, result), **(query or {"code": CODE})}
    done = await hass.config_entries.flow.async_configure(result["flow_id"], callback)
    assert done["type"] is FlowResultType.EXTERNAL_STEP_DONE
    return await hass.config_entries.flow.async_configure(result["flow_id"])


async def _link(hass: HomeAssistant) -> dict[str, Any]:
    """Open the flow and keep the default: Link account."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    return await hass.config_entries.flow.async_configure(result["flow_id"], {})


async def _pick_and_admit(
    hass: HomeAssistant, result: dict[str, Any]
) -> dict[str, Any]:
    assert result["type"] is FlowResultType.FORM, result
    assert result["step_id"] == "hub"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HUB_ID: HUB_ID}
    )
    assert result["type"] is FlowResultType.SHOW_PROGRESS
    await hass.async_block_till_done()
    return await hass.config_entries.flow.async_configure(result["flow_id"])


def _method_field(result: dict[str, Any]) -> tuple[Any, SelectSelector[Any]]:
    schema = result["data_schema"].schema
    key = next(key for key in schema if key == "link_method")
    return key, schema[key]


async def test_link_account_is_the_first_choice(hass: HomeAssistant) -> None:
    """The first step offers Link account by default, a code, and a private hub."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    key, selector = _method_field(result)
    assert key.default() == LINK_ACCOUNT == "link_account"
    assert selector.config["options"] == [LINK_ACCOUNT, LINK_CODE]
    assert selector.config["translation_key"] == "link_method"
    assert [str(key) for key in result["data_schema"].schema] == [
        "link_method",
        CONF_SELF_HOSTED,
    ]


@pytest.mark.usefixtures("my_home_assistant")
async def test_link_account(
    hass: HomeAssistant,
    token_endpoint: AiohttpClientMocker,
    mock_auth: MagicMock,
    mock_api: MagicMock,
    credentials: ConnectionCredentials,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Approve in the browser, come back through My Home Assistant, link a hub."""
    freezer.move_to("2026-11-08T12:00:00+00:00")
    hass.config.location_name = "Home"
    result = await _link(hass)

    query = _query(result)
    assert URL(result["url"]).with_query(None) == URL(
        "https://dash.thalovant.com/authorize"
    )
    challenge = query.pop("code_challenge")
    query.pop("state")
    assert query == {
        "response_type": "code",
        "client_id": "thalovant-home-assistant",
        "redirect_uri": "https://my.home-assistant.io/redirect/oauth",
        "code_challenge_method": "S256",
        "scope": "hubs:read clients:read clients:write",
        "device_name": "Home Assistant (Home)",
    }
    assert _state(hass, result) == {
        "flow_id": result["flow_id"],
        "redirect_uri": MY_AUTH_CALLBACK_PATH,
    }
    # Nothing is asked of Thalovant until the browser comes back.
    assert token_endpoint.call_count == 0

    result = await _come_back(hass, result)
    assert result["step_id"] == "hub"
    assert result["description_placeholders"] == {"account": "Gaëtan"}

    # Exactly the four fields, and the verifier whose challenge went out.
    assert token_endpoint.call_count == 1
    method, url, body, _ = token_endpoint.mock_calls[0]
    assert (method, str(url)) == ("POST", LINK_TOKEN_URL)
    assert set(body) == {"code", "code_verifier", "client_id", "redirect_uri"}
    assert body["code"] == CODE
    assert body["client_id"] == "thalovant-home-assistant"
    assert body["redirect_uri"] == MY_AUTH_CALLBACK_PATH
    assert _challenge(body["code_verifier"]) == challenge
    mock_auth.start_device_login.assert_not_awaited()

    result = await _pick_and_admit(hass, result)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Maison"
    assert result["result"].unique_id == f"{ACCOUNT_ID}:{HUB_ID}"
    assert result["data"] == {
        CONF_ACCOUNT_ID: ACCOUNT_ID,
        CONF_HUB_ID: HUB_ID,
        CONF_HUB_NAME: "Maison",
        CONF_TOKENS: LINKED.to_dict(),
        CONF_CREDENTIALS: credentials.to_dict(),
        CONF_LINKED_AT: "2026-11-08T12:00:00+00:00",
    }
    # The entry holds the token now: it is not revoked.
    await hass.async_block_till_done(wait_background_tasks=True)
    mock_api.revoke_token.assert_not_awaited()


@pytest.mark.usefixtures("my_home_assistant", "token_endpoint", "mock_auth")
async def test_link_account_through_the_callback_view(
    hass: HomeAssistant, hass_client_no_auth: Any, mock_api: MagicMock
) -> None:
    """Home Assistant's own callback page resumes the flow with the code."""
    result = await _link(hass)
    hass.http.register_view(OAuth2AuthorizeCallbackView())
    client = await hass_client_no_auth()

    # A state this Home Assistant did not sign is refused, and the flow waits.
    response = await client.get(
        "/auth/external/callback", params={"code": CODE, "state": "forged"}
    )
    assert response.status == 400
    assert hass.config_entries.flow.async_get(result["flow_id"])["step_id"] == "auth"

    response = await client.get(
        "/auth/external/callback",
        params={"code": CODE, "state": _query(result)["state"]},
    )
    assert response.status == 200
    result = await hass.config_entries.flow.async_configure(result["flow_id"])
    assert result["step_id"] == "hub"


@pytest.mark.usefixtures("my_home_assistant", "mock_auth", "mock_api")
async def test_link_account_invalid_grant(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """invalid_grant says the approval likely came from another network.

    Thalovant spends a code exchanged from another network than the one that
    approved it, and answers 400 invalid_grant, as it does for an expired or
    reused code. The first step says which is likeliest; linking again starts
    afresh.
    """
    aioclient_mock.post(LINK_TOKEN_URL, status=400, json={"detail": "invalid_grant"})
    first = await _link(hass)
    result = await _come_back(hass, first)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "link_wrong_network"}
    assert _method_field(result)[0].default() == LINK_ACCOUNT
    assert "did not accept the approval (HTTP 400, invalid_grant)" in caplog.text
    assert CODE not in caplog.text

    aioclient_mock.clear_requests()
    aioclient_mock.post(LINK_TOKEN_URL, json=ANSWER)
    second = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    # A new attempt, so a new verifier.
    assert _query(second)["code_challenge"] != _query(first)["code_challenge"]
    result = await _come_back(hass, second)
    assert result["step_id"] == "hub"


@pytest.mark.parametrize(
    ("answer", "error"),
    [
        ({"status": 503}, "cannot_connect"),
        ({"status": 429}, "cannot_connect"),
        ({"exc": aiohttp.ClientConnectionError()}, "cannot_connect"),
        ({"exc": TimeoutError()}, "cannot_connect"),
        ({"status": 404, "json": {"detail": "Not Found"}}, "link_failed"),
        # A 400 that does not say invalid_grant claims nothing about networks.
        ({"status": 400, "json": {"detail": "invalid_request"}}, "link_failed"),
        ({"status": 400, "text": ""}, "link_failed"),
        ({"json": {"token_type": "bearer"}}, "unknown"),
        ({"text": "<html></html>"}, "unknown"),
    ],
)
@pytest.mark.usefixtures("my_home_assistant", "mock_auth", "mock_api")
async def test_link_account_exchange_errors(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    answer: dict[str, Any],
    error: str,
) -> None:
    """A failed exchange says why on the first step."""
    aioclient_mock.post(LINK_TOKEN_URL, **answer)
    result = await _come_back(hass, await _link(hass))
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": error}


@pytest.mark.usefixtures("my_home_assistant", "token_endpoint", "mock_auth")
async def test_link_account_unexpected_error(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Anything unexpected is logged and reported as unknown."""
    with patch(
        "custom_components.thalovant.config_flow.tokens_from_answer",
        side_effect=RuntimeError("boom"),
    ):
        result = await _come_back(hass, await _link(hass))
    assert result["errors"] == {"base": "unknown"}
    assert "Unexpected error while linking the account" in caplog.text


@pytest.mark.parametrize(
    ("reason", "error"),
    [("access_denied", "login_denied"), ("invalid_scope", "link_failed")],
)
@pytest.mark.usefixtures("my_home_assistant", "mock_auth")
async def test_link_account_declined(
    hass: HomeAssistant,
    token_endpoint: AiohttpClientMocker,
    reason: str,
    error: str,
) -> None:
    """Declining on the consent page, or a refusal, goes back to the first step."""
    result = await _come_back(hass, await _link(hass), error=reason)
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": error}
    assert token_endpoint.call_count == 0


async def test_without_my_home_assistant_a_code_is_offered(
    hass: HomeAssistant,
    mock_auth: MagicMock,
    mock_api: MagicMock,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """No My Home Assistant: say so, and link with the device login instead."""
    result = await _link(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "no_my_home_assistant"
    mock_auth.start_device_login.assert_not_awaited()

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.SHOW_PROGRESS
    assert result["step_id"] == "login"
    mock_auth.start_device_login.assert_awaited_once()
    await hass.async_block_till_done()
    result = await hass.config_entries.flow.async_configure(result["flow_id"])
    result = await _pick_and_admit(hass, result)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert aioclient_mock.call_count == 0


@pytest.mark.usefixtures("current_request_with_host", "mock_auth")
async def test_own_address_is_not_enough(hass: HomeAssistant) -> None:
    """A redirect to this installation's own address gets the code offer too."""
    result = await _link(hass)
    assert result["step_id"] == "no_my_home_assistant"


async def test_code_choice_sticks_after_an_error(
    hass: HomeAssistant, mock_auth: MagicMock
) -> None:
    """After a failed code, the first step offers the code again."""
    mock_auth.start_device_login.side_effect = ThalovantConnectionError("dns")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"link_method": LINK_CODE}
    )
    assert result["errors"] == {"base": "cannot_connect"}
    assert _method_field(result)[0].default() == LINK_CODE


@pytest.mark.usefixtures("my_home_assistant", "token_endpoint", "mock_auth")
async def test_link_account_no_hubs_revokes_the_token(
    hass: HomeAssistant, mock_api: MagicMock
) -> None:
    """A token minted for nothing is revoked, as after a code."""
    mock_api.list_hubs.return_value = []
    result = await _come_back(hass, await _link(hass))
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_hubs"
    await hass.async_block_till_done(wait_background_tasks=True)
    mock_api.revoke_token.assert_awaited_once_with()


@pytest.mark.usefixtures("my_home_assistant", "mock_auth")
async def test_closed_while_approving(
    hass: HomeAssistant, token_endpoint: AiohttpClientMocker, mock_api: MagicMock
) -> None:
    """Closing the dialog before the browser comes back leaves nothing behind."""
    result = await _link(hass)
    hass.config_entries.flow.async_abort(result["flow_id"])
    await hass.async_block_till_done(wait_background_tasks=True)
    with pytest.raises(UnknownFlow):
        hass.config_entries.flow.async_get(result["flow_id"])
    assert token_endpoint.call_count == 0
    mock_api.revoke_token.assert_not_awaited()


@pytest.mark.usefixtures("my_home_assistant", "token_endpoint", "mock_auth")
async def test_link_account_moves_the_accounts_links_to_it(
    hass: HomeAssistant,
    mock_api: MagicMock,
    mock_config_entry: MockConfigEntry,
    tokens: Tokens,
) -> None:
    """Approving again replaces the app's token, so every link moves to the new one."""
    mock_config_entry.add_to_hass(hass)
    result = await _come_back(hass, await _link(hass))
    assert result["step_id"] == "hub"
    assert mock_config_entry.data[CONF_TOKENS] == LINKED.to_dict()
    await hass.async_block_till_done(wait_background_tasks=True)
    # The replaced token is revoked in case it was still alive.
    mock_api.revoke_token.assert_awaited_once_with()


@pytest.mark.usefixtures("my_home_assistant")
async def test_reauth_links_account(
    hass: HomeAssistant,
    token_endpoint: AiohttpClientMocker,
    mock_auth: MagicMock,
    mock_api: MagicMock,
    mock_config_entry: MockConfigEntry,
    account: Account,
    credentials: ConnectionCredentials,
) -> None:
    """Reauth tries the stored token, then links the account the same way."""
    mock_config_entry.add_to_hass(hass)
    mock_api.get_account.side_effect = [ThalovantAuthError("revoked"), account]
    mock_api.create_connection.return_value = replace(
        credentials, connection_id="conn-new"
    )
    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    key, _ = _method_field(result)
    assert key.default() == LINK_ACCOUNT
    assert [str(key) for key in result["data_schema"].schema] == ["link_method"]

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert _state(hass, result)["flow_id"] == result["flow_id"]
    result = await _come_back(hass, result)
    assert result["type"] is FlowResultType.SHOW_PROGRESS
    assert result["step_id"] == "admission"
    await hass.async_block_till_done()
    result = await hass.config_entries.flow.async_configure(result["flow_id"])
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"

    assert mock_config_entry.data[CONF_TOKENS] == LINKED.to_dict()
    assert mock_config_entry.data[CONF_CREDENTIALS]["connection_id"] == "conn-new"
    mock_api.delete_connection.assert_awaited_once_with(CONNECTION_ID)
    mock_auth.start_device_login.assert_not_awaited()
    assert token_endpoint.call_count == 1


@pytest.mark.usefixtures("my_home_assistant", "token_endpoint", "mock_auth")
async def test_reauth_link_failure_returns_to_confirm(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_api: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A refused code during reauth comes back to reauth's own first step."""
    aioclient_mock.clear_requests()
    aioclient_mock.post(LINK_TOKEN_URL, status=400, json={"detail": "invalid_grant"})
    mock_api.get_account.side_effect = ThalovantAuthError("revoked")
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    result = await _come_back(hass, result)
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": "link_wrong_network"}


@pytest.mark.usefixtures("my_home_assistant")
async def test_entry_stored_by_0_2_renews_with_link_account(
    hass: HomeAssistant,
    token_endpoint: AiohttpClientMocker,
    mock_auth: MagicMock,
    mock_api: MagicMock,
    entry_stored_by_0_2: MockConfigEntry,
    account: Account,
    credentials: ConnectionCredentials,
) -> None:
    """Reauth of an entry 0.2.5 stored: its token first, then Link account."""
    entry_stored_by_0_2.add_to_hass(hass)
    stored = Tokens.from_dict(entry_stored_by_0_2.data[CONF_TOKENS])
    mock_api.get_account.side_effect = [ThalovantAuthError("revoked"), account]
    mock_api.create_connection.return_value = replace(
        credentials, connection_id="conn-new"
    )
    with patch(
        "custom_components.thalovant.config_flow.ThalovantApi", return_value=mock_api
    ) as api_class:
        result = await entry_stored_by_0_2.start_reauth_flow(hass)
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        # The stored token was tried first, as read from the 0.2 entry.
        assert api_class.call_args_list[0].args[1] == stored
        result = await _come_back(hass, result)
        await hass.async_block_till_done()
        result = await hass.config_entries.flow.async_configure(result["flow_id"])
    assert result["reason"] == "reauth_successful"
    assert set(entry_stored_by_0_2.data) == {
        CONF_ACCOUNT_ID,
        CONF_HUB_ID,
        CONF_HUB_NAME,
        CONF_TOKENS,
        CONF_CREDENTIALS,
        CONF_LINKED_AT,
    }
    assert entry_stored_by_0_2.data[CONF_TOKENS] == LINKED.to_dict()
    assert entry_stored_by_0_2.data[CONF_CREDENTIALS]["connection_id"] == "conn-new"
    mock_api.delete_connection.assert_awaited_once_with(CONNECTION_ID)


@pytest.mark.usefixtures("my_home_assistant", "mock_auth")
async def test_closed_while_thalovant_answers(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_api: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A token that arrives after the dialog closed is revoked, not kept.

    Home Assistant removes the flow while the exchange is in flight; the
    step still gets the token, which nothing will hold, and nothing else
    changes: no account read, no other entry handed the token.
    """
    mock_config_entry.add_to_hass(hass)
    before = dict(mock_config_entry.data)
    result = await _link(hass)
    flow_id = result["flow_id"]

    async def close_then_answer(*_: Any) -> AiohttpClientMockResponse:
        hass.config_entries.flow.async_abort(flow_id)
        return AiohttpClientMockResponse("POST", URL(LINK_TOKEN_URL), json=ANSWER)

    aioclient_mock.post(LINK_TOKEN_URL, side_effect=close_then_answer)
    done = await hass.config_entries.flow.async_configure(
        flow_id, {"state": _state(hass, result), "code": CODE}
    )
    assert done["type"] is FlowResultType.EXTERNAL_STEP_DONE
    result = await hass.config_entries.flow.async_configure(flow_id)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "link_closed"

    await hass.async_block_till_done(wait_background_tasks=True)
    mock_api.revoke_token.assert_awaited_once_with()
    mock_api.get_account.assert_not_awaited()
    assert dict(mock_config_entry.data) == before


@pytest.mark.usefixtures("my_home_assistant", "token_endpoint")
async def test_entries_are_the_same_either_way(
    hass: HomeAssistant, mock_auth: MagicMock, mock_api: MagicMock
) -> None:
    """Link account stores what a code stores, so entries from 0.2 need nothing.

    Same keys, same token form, same entry version: an entry linked with a
    code before 0.3.0 loads and renews exactly as one linked with the browser.
    """
    linked = await _pick_and_admit(hass, await _come_back(hass, await _link(hass)))
    linked_entry = linked["result"]
    await hass.config_entries.async_remove(linked_entry.entry_id)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"link_method": LINK_CODE}
    )
    await hass.async_block_till_done()
    result = await hass.config_entries.flow.async_configure(result["flow_id"])
    coded = await _pick_and_admit(hass, result)

    assert set(coded["data"]) == set(linked["data"])
    assert set(coded["data"][CONF_TOKENS]) == set(linked["data"][CONF_TOKENS])
    assert Tokens.from_dict(linked["data"][CONF_TOKENS]) == LINKED
    assert (linked_entry.version, linked_entry.minor_version) == (1, 1)
    assert (ThalovantConfigFlow.VERSION, ThalovantConfigFlow.MINOR_VERSION) == (1, 1)


def test_flow_logger() -> None:
    """Home Assistant's OAuth 2 steps log under the integration."""
    assert ThalovantConfigFlow().logger.name == "custom_components.thalovant"
