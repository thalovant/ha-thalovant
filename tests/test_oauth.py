"""Link account's OAuth 2 implementation: the authorize URL and the JSON exchange.

The exchange runs over Home Assistant's own client session against a local
token endpoint, so the tests see what goes on the wire.
"""

import base64
from collections.abc import AsyncIterator
from datetime import UTC, datetime
import hashlib
import json
import re
from typing import Any

from aiohttp import web
from aiohttp.test_utils import TestServer
import pytest
from yarl import URL

from custom_components.thalovant.api import (
    ThalovantApiError,
    ThalovantConnectionError,
    Tokens,
)
from custom_components.thalovant.const import (
    LINK_AUTHORIZE_URL,
    LINK_CLIENT_ID,
    LINK_TOKEN_URL,
    LOGIN_SCOPES,
)
from custom_components.thalovant.oauth import (
    LinkRejectedError,
    ThalovantOAuth2Implementation,
    tokens_from_answer,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.config_entry_oauth2_flow import MY_AUTH_CALLBACK_PATH

CODE = "link-code-do-not-leak"
TOKEN_PATH = "/v1/auth/native/token"
ANSWER: dict[str, Any] = {
    "access_token": "tvt_link_access_do_not_leak",
    "token_type": "bearer",
    "scopes": ["hubs:read", "clients:read", "clients:write"],
    "expires_at": "2027-11-08T12:00:00Z",
    "token_id": "tok-link-1",
    "ai_disclosure": "Thalovant devices use AI.",
}
UNRESERVED = re.compile(r"[A-Za-z0-9._~-]+")


def _challenge(verifier: str) -> str:
    """RFC 7636 S256, computed here rather than with Home Assistant's helper."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


class TokenEndpoint:
    """Thalovant's native token endpoint, answering what the test sets."""

    def __init__(self) -> None:
        """Answer 200 with a token until told otherwise."""
        self.status = 200
        self.body: str = json.dumps(ANSWER)
        self.requests: list[tuple[str | None, Any]] = []
        self.url = ""

    async def handle(self, request: web.Request) -> web.Response:
        """Record the request's type and body, then answer."""
        self.requests.append((request.content_type, json.loads(await request.text())))
        return web.Response(
            status=self.status, text=self.body, content_type="application/json"
        )


@pytest.fixture
async def token_endpoint(socket_enabled: None) -> AsyncIterator[TokenEndpoint]:
    """A local token endpoint on 127.0.0.1."""
    endpoint = TokenEndpoint()
    app = web.Application()
    app.router.add_post(TOKEN_PATH, endpoint.handle)
    server = TestServer(app, host="127.0.0.1")
    await server.start_server()
    endpoint.url = f"http://127.0.0.1:{server.port}{TOKEN_PATH}"
    yield endpoint
    await server.close()


def _implementation(
    hass: HomeAssistant, endpoint: TokenEndpoint | None = None
) -> ThalovantOAuth2Implementation:
    implementation = ThalovantOAuth2Implementation(
        hass, device_name="Home Assistant (Home)"
    )
    if endpoint is not None:
        implementation.token_url = endpoint.url
    return implementation


def _came_back() -> dict[str, Any]:
    """What the callback view hands the flow: the code and the decoded state."""
    return {
        "code": CODE,
        "state": {"flow_id": "flow-1", "redirect_uri": MY_AUTH_CALLBACK_PATH},
    }


def test_endpoints() -> None:
    """The app, the consent page and the token endpoint the API answers."""
    assert LINK_CLIENT_ID == "thalovant-home-assistant"
    assert LINK_AUTHORIZE_URL == "https://dash.thalovant.com/authorize"
    assert LINK_TOKEN_URL == "https://api.thalovant.com/v1/auth/native/token"


@pytest.mark.usefixtures("my_home_assistant")
async def test_authorize_url_carries_every_parameter(hass: HomeAssistant) -> None:
    """The consent page gets exactly the standard parameters, PKCE and the name."""
    implementation = _implementation(hass)
    url = URL(await implementation.async_generate_authorize_url("flow-1"))

    assert str(url.with_query(None)) == "https://dash.thalovant.com/authorize"
    query = dict(url.query)
    state = query.pop("state")
    assert query == {
        "response_type": "code",
        "client_id": "thalovant-home-assistant",
        "redirect_uri": "https://my.home-assistant.io/redirect/oauth",
        "code_challenge": _challenge(implementation.code_verifier),
        "code_challenge_method": "S256",
        "scope": "hubs:read clients:read clients:write",
        "device_name": "Home Assistant (Home)",
    }
    assert len(url.query.getall("scope")) == 1
    assert " " not in url.raw_query_string
    # The state is signed with this Home Assistant's own secret and names the
    # flow to resume and the redirect the code was sent to.
    assert config_entry_oauth2_flow._decode_jwt(hass, state) == {
        "flow_id": "flow-1",
        "redirect_uri": MY_AUTH_CALLBACK_PATH,
    }
    assert "scope" not in implementation.extra_token_resolve_data


def test_rfc_7636_vector() -> None:
    """The challenge is S256 of the verifier, as RFC 7636 Appendix B has it."""
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    expected = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    assert ThalovantOAuth2Implementation.compute_code_challenge(verifier) == expected
    assert _challenge(verifier) == expected


async def test_each_link_has_its_own_verifier(hass: HomeAssistant) -> None:
    """A verifier per attempt, 43 to 128 unreserved characters."""
    first, second = _implementation(hass), _implementation(hass)
    assert first.code_verifier != second.code_verifier
    for verifier in (first.code_verifier, second.code_verifier):
        assert 43 <= len(verifier) <= 128
        assert UNRESERVED.fullmatch(verifier)


async def test_device_name_is_capped(hass: HomeAssistant) -> None:
    """The consent page takes 120 characters of the name at most."""
    hass.config.components.add("my")
    implementation = ThalovantOAuth2Implementation(hass, device_name="x" * 300)
    url = URL(await implementation.async_generate_authorize_url("flow-1"))
    assert url.query["device_name"] == "x" * 120


async def test_name(hass: HomeAssistant) -> None:
    """The name Home Assistant would show if it ever listed implementations."""
    assert _implementation(hass).name == "Thalovant"


async def test_redirect_through_my_home_assistant(hass: HomeAssistant) -> None:
    """Only My Home Assistant's redirect counts."""
    assert not _implementation(hass).through_my_home_assistant
    hass.config.components.add("my")
    assert _implementation(hass).through_my_home_assistant


@pytest.mark.usefixtures("current_request_with_host")
async def test_own_address_is_not_my_home_assistant(hass: HomeAssistant) -> None:
    """A redirect to this installation's own address is not what Thalovant answers."""
    implementation = _implementation(hass)
    assert implementation.redirect_uri == "https://example.com/auth/external/callback"
    assert not implementation.through_my_home_assistant


async def test_exchange_posts_json(
    hass: HomeAssistant, token_endpoint: TokenEndpoint
) -> None:
    """The code, the verifier, the app and the redirect, as JSON, nothing else."""
    implementation = _implementation(hass, token_endpoint)
    answer = await implementation.async_resolve_external_data(_came_back())

    assert answer == ANSWER
    assert token_endpoint.requests == [
        (
            "application/json",
            {
                "code": CODE,
                "code_verifier": implementation.code_verifier,
                "client_id": "thalovant-home-assistant",
                "redirect_uri": "https://my.home-assistant.io/redirect/oauth",
            },
        )
    ]


@pytest.mark.parametrize(
    ("status", "body", "error"),
    [
        (400, '{"detail": "invalid_grant"}', LinkRejectedError),
        (400, "", LinkRejectedError),
        (401, '{"detail": "Not authenticated"}', LinkRejectedError),
        (404, '{"detail": "Not Found"}', LinkRejectedError),
        (429, '{"detail": "Too many requests"}', ThalovantConnectionError),
        (500, "oops", ThalovantConnectionError),
        (503, "", ThalovantConnectionError),
        (200, "<html>not json</html>", ThalovantApiError),
        (200, '["not", "an", "object"]', ThalovantApiError),
    ],
)
async def test_exchange_errors(
    hass: HomeAssistant,
    token_endpoint: TokenEndpoint,
    status: int,
    body: str,
    error: type[Exception],
) -> None:
    """Each failure has its type, and no message names the code or the verifier."""
    token_endpoint.status = status
    token_endpoint.body = body
    implementation = _implementation(hass, token_endpoint)
    with pytest.raises(error) as caught:
        await implementation.async_resolve_external_data(_came_back())
    if status != 200:
        assert getattr(caught.value, "status", None) == status
    for text in (str(caught.value), repr(caught.value)):
        assert CODE not in text
        assert implementation.code_verifier not in text


async def test_exchange_unreachable(hass: HomeAssistant, socket_enabled: None) -> None:
    """Nothing listening is a connection error."""
    implementation = _implementation(hass)
    implementation.token_url = f"http://127.0.0.1:9{TOKEN_PATH}"
    with pytest.raises(ThalovantConnectionError) as caught:
        await implementation.async_resolve_external_data(_came_back())
    assert CODE not in str(caught.value)


async def test_no_refresh_token(hass: HomeAssistant) -> None:
    """There is nothing to refresh: the token lives a year, then reauth."""
    with pytest.raises(ThalovantApiError):
        await _implementation(hass)._async_refresh_token({"access_token": "x"})


def test_tokens_from_answer() -> None:
    """The answer is read the way the SDK reads a device login's."""
    assert tokens_from_answer(ANSWER) == Tokens(
        access_token="tvt_link_access_do_not_leak",
        expires_at=datetime(2027, 11, 8, 12, tzinfo=UTC),
        scopes=("hubs:read", "clients:read", "clients:write"),
        token_id="tok-link-1",
    )


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        (
            {"access_token": "a"},
            Tokens(access_token="a", expires_at=None, scopes=(), token_id=None),
        ),
        (
            {
                "access_token": "a",
                "scopes": ["hubs:read", 7],
                "expires_at": "not a date",
                "token_id": "",
            },
            Tokens(
                access_token="a", expires_at=None, scopes=("hubs:read",), token_id=None
            ),
        ),
        (
            {
                "access_token": "a",
                "scopes": "hubs:read",
                "expires_at": 1,
                "token_id": 5,
            },
            Tokens(access_token="a", expires_at=None, scopes=(), token_id=None),
        ),
    ],
)
def test_tokens_from_answer_is_lenient(
    answer: dict[str, Any], expected: Tokens
) -> None:
    """Scopes, expiry and id it cannot read are left out, as the SDK does."""
    assert tokens_from_answer(answer) == expected


@pytest.mark.parametrize("access_token", [None, "", 5])
def test_tokens_from_answer_needs_a_token(access_token: Any) -> None:
    """An answer without an access token is an error."""
    with pytest.raises(ThalovantApiError):
        tokens_from_answer({"access_token": access_token, "token_id": "tok"})


def test_link_asks_for_the_device_login_scopes() -> None:
    """Both sign-ins ask for the same three permissions."""
    assert LOGIN_SCOPES == ("hubs:read", "clients:read", "clients:write")
