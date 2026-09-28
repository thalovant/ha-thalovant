"""The adapter against the real thalovant SDK and a local control plane.

Skipped unless the SDK is installed. CI installs it from the SDK branch in a
step of its own; locally:

    uv pip install --no-deps "thalovant @ git+https://github.com/thalovant/thalovant-python-sdk@feat/async-core"

--no-deps because Home Assistant 2026.9 pins cryptography 48.0.1 and thalovant
0.9.0 asks for 50 or later; the SDK runs on 48 for what this exercises.
"""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from aiohttp import ClientSession, web
from aiohttp.test_utils import TestServer
import pytest

from custom_components.thalovant import api
from custom_components.thalovant.api import (
    ConnectionCredentials,
    DeviceLoginPending,
    HubConnection,
    ThalovantAdmissionFailedError,
    ThalovantAdmissionTimeoutError,
    ThalovantAlreadyLinkedError,
    ThalovantApi,
    ThalovantApiError,
    ThalovantAuth,
    ThalovantAuthError,
    ThalovantConnectionError,
    ThalovantPlanError,
    ThalovantUnsupportedError,
    Tokens,
)
from custom_components.thalovant.const import (
    CONNECTION_KIND,
    LOGIN_SCOPES,
    REQUEST_MESSAGE_TYPE,
    RESPONSE_MESSAGE_TYPE,
)

thalovant = pytest.importorskip("thalovant")

# The local control plane listens on 127.0.0.1.
pytestmark = pytest.mark.usefixtures("socket_enabled")

ACCOUNT = "acct-1"
TOKEN = "tvt_access"
HUB = "hub-maison"
PUBLIC_HUB = "hub-daily-desk"
CLIENT = "conn-1"


class ControlPlane:
    """Enough of the Thalovant API for the calls the adapter makes."""

    def __init__(self) -> None:
        """Start with a sign-in that is approved on the third poll."""
        self.token_answers: list[tuple[int, dict[str, Any]]] = [
            (400, {"error": "slow_down"}),
            (400, {"error": "authorization_pending"}),
            (
                200,
                {
                    "access_token": TOKEN,
                    "token_type": "bearer",
                    "scopes": list(LOGIN_SCOPES),
                    "expires_at": "2027-09-27T00:00:00Z",
                    "token_id": "tok-1",
                },
            ),
        ]
        self.create_answer: tuple[int, dict[str, Any]] | None = None
        self.operation_status = "ready"
        # False plays an API that silently drops spec.connection_type.
        self.echo_kind = True
        self.requests: list[tuple[str, str, Any]] = []
        self.deleted: list[tuple[str, str | None]] = []
        self.revoked: list[str] = []

    def app(self) -> web.Application:
        """The routes."""
        app = web.Application()
        app.router.add_post("/v1/auth/device/authorize", self.authorize)
        app.router.add_post("/v1/auth/device/token", self.token)
        app.router.add_get("/v1/users/profile", self.profile)
        app.router.add_get("/v1/hubs", self.hubs)
        app.router.add_get("/v1/hubs/{hub}", self.hub)
        app.router.add_get("/v1/public/hubs", self.public_hubs)
        app.router.add_post("/v1/clients", self.create_client)
        app.router.add_get("/v1/clients/{client}", self.client)
        app.router.add_delete("/v1/clients/{client}", self.delete_client)
        app.router.add_get("/v1/operations/{operation}", self.operation)
        app.router.add_delete("/v1/auth/api-tokens/{token}", self.revoke)
        return app

    def _authorized(self, request: web.Request) -> None:
        if request.headers.get("Authorization") != f"Bearer {TOKEN}":
            raise web.HTTPUnauthorized(
                text='{"detail": "Not authenticated"}', content_type="application/json"
            )

    async def authorize(self, request: web.Request) -> web.Response:
        self.requests.append(("authorize", request.path, await request.json()))
        return web.json_response(
            {
                "device_code": "device-code-0123456789",
                "user_code": "WXYZ-2345",
                "verification_uri": "https://dash.thalovant.com/device",
                "verification_uri_complete": "https://dash.thalovant.com/device?code=WXYZ-2345",
                "expires_in": 900,
                "interval": 5,
            }
        )

    async def token(self, request: web.Request) -> web.Response:
        status, body = self.token_answers.pop(0)
        return web.json_response(body, status=status)

    async def profile(self, request: web.Request) -> web.Response:
        self._authorized(request)
        return web.json_response(
            {
                "data": {
                    "id": ACCOUNT,
                    "email": "g@example.com",
                    "display_name": "Gaëtan",
                }
            }
        )

    async def hubs(self, request: web.Request) -> web.Response:
        self._authorized(request)
        self.requests.append(("hubs", request.path_qs, None))
        if request.query.get("cursor") == "page-2":
            return web.json_response(
                {
                    "data": [
                        {
                            "id": "hub-old",
                            "name": "old",
                            "slug": "old",
                            "is_locked": True,
                        }
                    ],
                    "meta": {"count": 1, "next": None},
                }
            )
        return web.json_response(
            {
                "data": [
                    {
                        "id": HUB,
                        "name": "maison",
                        "slug": "maison",
                        "spec": {"catalog": {"title": "Maison"}},
                    }
                ],
                "meta": {"count": 1, "next": "page-2"},
            }
        )

    async def public_hubs(self, request: web.Request) -> web.Response:
        return web.json_response(
            {
                "data": [
                    {
                        "id": PUBLIC_HUB,
                        "name": "daily-desk",
                        "slug": "daily-desk",
                        "title": "Daily Desk",
                    },
                    {"id": HUB, "name": "maison", "slug": "maison", "title": "Maison"},
                ],
                "meta": {"count": 2, "next": None},
            }
        )

    async def hub(self, request: web.Request) -> web.Response:
        self._authorized(request)
        return web.json_response(
            {
                "id": request.match_info["hub"],
                "name": "maison",
                "slug": "maison",
                "domain": "maison.hubs.example",
                "spec": {},
                "data_plane_endpoints": {"wss": "wss://maison.hubs.example"},
            }
        )

    async def create_client(self, request: web.Request) -> web.Response:
        self._authorized(request)
        body = await request.json()
        self.requests.append(("create", request.path, body))
        if self.create_answer is not None:
            status, problem = self.create_answer
            return web.json_response(problem, status=status)
        spec = body["spec"]
        return web.json_response(
            {
                "id": CLIENT,
                "name": body["name"],
                "etag": "etag-1",
                "spec": {
                    "version": "1",
                    "connection_type": spec.get("connection_type")
                    if self.echo_kind
                    else None,
                },
                "initial_identify": {
                    "access_key": spec["apiKey"],
                    "password": spec["password"],
                    "site_id": spec["siteId"],
                    "default_master": "maison.hubs.example",
                    "default_port": 443,
                },
                "operation": {
                    "id": "op-1",
                    "kind": "client.create",
                    "aggregate_type": "client",
                    "aggregate_id": CLIENT,
                    "status": "requested",
                    "created_at": "2026-09-27T00:00:00Z",
                    "updated_at": "2026-09-27T00:00:00Z",
                    "links": {"self": "/v1/operations/op-1"},
                },
            },
            status=201,
        )

    async def client(self, request: web.Request) -> web.Response:
        self._authorized(request)
        return web.json_response({"id": request.match_info["client"], "etag": "etag-1"})

    async def delete_client(self, request: web.Request) -> web.Response:
        self._authorized(request)
        self.deleted.append(
            (request.match_info["client"], request.headers.get("If-Match"))
        )
        return web.Response(status=204)

    async def operation(self, request: web.Request) -> web.Response:
        self._authorized(request)
        return web.json_response(
            {
                "id": request.match_info["operation"],
                "kind": "client.create",
                "aggregate_type": "client",
                "status": self.operation_status,
                "error_code": "sync_failed"
                if self.operation_status == "failed"
                else None,
                "created_at": "2026-09-27T00:00:00Z",
                "updated_at": "2026-09-27T00:00:00Z",
            }
        )

    async def revoke(self, request: web.Request) -> web.Response:
        self._authorized(request)
        self.revoked.append(request.match_info["token"])
        return web.Response(status=204)


@pytest.fixture
async def control_plane() -> AsyncIterator[tuple[ControlPlane, str, ClientSession]]:
    """A local control plane, its URL, and a session to reach it."""
    plane = ControlPlane()
    server = TestServer(plane.app(), host="127.0.0.1")
    await server.start_server()
    async with ClientSession() as session:
        yield plane, f"http://127.0.0.1:{server.port}", session
    await server.close()


def _tokens() -> Tokens:
    return Tokens(TOKEN, None, LOGIN_SCOPES, "tok-1")


def test_sdk_has_every_name() -> None:
    """Everything the adapter takes from the SDK is there, under that name."""
    assert api._sdk_module is thalovant
    assert [name for name in api.SDK_NAMES if not hasattr(thalovant, name)] == []


def test_constants_match_the_sdk() -> None:
    """The integration's scopes, kind and message types are the SDK's."""
    assert tuple(LOGIN_SCOPES) == tuple(thalovant.HOME_ASSISTANT_SCOPES)
    assert CONNECTION_KIND == thalovant.CONNECTION_TYPE_HOME_ASSISTANT
    assert REQUEST_MESSAGE_TYPE == thalovant.HOME_REQUEST
    assert RESPONSE_MESSAGE_TYPE == thalovant.HOME_RESPONSE


async def test_device_login(
    control_plane: tuple[ControlPlane, str, ClientSession],
) -> None:
    """A sign-in: the code, a slow_down that lengthens the wait, then the token."""
    plane, url, session = control_plane
    auth = ThalovantAuth(session, api_url=url)
    login = await auth.start_device_login(
        client_name="Home Assistant (Home)", scopes=LOGIN_SCOPES
    )
    assert login.user_code == "WXYZ-2345"
    assert login.interval == 5.0
    assert plane.requests[0][2] == {
        "scopes": list(LOGIN_SCOPES),
        "client_name": "Home Assistant (Home)",
    }

    with pytest.raises(DeviceLoginPending) as slow:
        await auth.poll_device_login(login)
    assert slow.value.interval == 10.0
    with pytest.raises(DeviceLoginPending) as pending:
        await auth.poll_device_login(login)
    assert pending.value.interval == 10.0

    tokens = await auth.poll_device_login(login)
    assert tokens.access_token == TOKEN
    assert tokens.token_id == "tok-1"
    assert tokens.scopes == LOGIN_SCOPES
    assert Tokens.from_dict(tokens.to_dict()) == tokens


async def test_account_and_hubs(
    control_plane: tuple[ControlPlane, str, ClientSession],
) -> None:
    """The account, then its own hubs by owner across pages, then the public ones."""
    plane, url, session = control_plane
    thalovant_api = ThalovantApi(session, _tokens(), api_url=url)
    account = await thalovant_api.get_account()
    assert (account.id, account.display_name, account.email) == (
        ACCOUNT,
        "Gaëtan",
        "g@example.com",
    )
    hubs = await thalovant_api.list_hubs()
    assert [(hub.id, hub.name) for hub in hubs] == [
        (HUB, "Maison"),
        (PUBLIC_HUB, "Daily Desk"),
    ]
    listed = [path for kind, path, _ in plane.requests if kind == "hubs"]
    assert all(f"owner_id={ACCOUNT}" in path for path in listed)
    assert len(listed) == 2


async def test_link_admit_delete_revoke(
    control_plane: tuple[ControlPlane, str, ClientSession],
    tmp_path: Path,
) -> None:
    """Create a Home Assistant connection, wait for it, store it, then undo it all."""
    plane, url, session = control_plane
    thalovant_api = ThalovantApi(session, _tokens(), api_url=url)
    credentials = await thalovant_api.create_connection(
        HUB, name="Home Assistant (Maison)", kind=CONNECTION_KIND
    )
    [(_, _, body)] = [request for request in plane.requests if request[0] == "create"]
    assert body["hub_id"] == HUB
    assert body["name"] == "Home Assistant (Maison)"
    assert body["spec"]["connection_type"] == "home_assistant"
    assert credentials.connection_id == CLIENT
    assert credentials.endpoint == "wss://maison.hubs.example"
    assert credentials.operation_url == "/v1/operations/op-1"
    assert credentials.secret["password"] == body["spec"]["password"]

    await thalovant_api.wait_for_admission(credentials, timeout=5)

    # What the entry stores is what the hub link is built from.
    stored = ConnectionCredentials.from_dict(credentials.to_dict())
    link = HubConnection(session, stored, state_dir=str(tmp_path / "noise"))
    assert link.connected is False
    unsubscribe = link.on_message(REQUEST_MESSAGE_TYPE, lambda message: None)
    stop = link.on_state_change(lambda up: None)
    unsubscribe()
    stop()
    await link.close()

    await thalovant_api.delete_connection(CLIENT)
    assert plane.deleted == [(CLIENT, "etag-1")]
    await thalovant_api.revoke_token()
    assert plane.revoked == ["tok-1"]


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ((402, {"detail": "Upgrade to link a hub you own."}), ThalovantPlanError),
        (
            (
                403,
                {
                    "detail": "Free plan allows up to 1 connection.",
                    "code": "plan_limit",
                },
            ),
            ThalovantPlanError,
        ),
        (
            (
                409,
                {
                    "detail": "Already linked.",
                    "code": "home_assistant_already_linked",
                    "client_id": "c-old",
                },
            ),
            ThalovantAlreadyLinkedError,
        ),
        (
            (
                422,
                {
                    "detail": [
                        {"loc": ["body", "spec", "connection_type"], "msg": "bad"}
                    ]
                },
            ),
            ThalovantUnsupportedError,
        ),
        ((401, {"detail": "Not authenticated"}), ThalovantAuthError),
        ((400, {"detail": "Name taken."}), ThalovantApiError),
        ((503, {"detail": "Down."}), ThalovantConnectionError),
    ],
)
async def test_create_refusals(
    control_plane: tuple[ControlPlane, str, ClientSession],
    answer: tuple[int, dict[str, Any]],
    expected: type[Exception],
) -> None:
    """Each refusal the API gives reaches the flow as the error it translates."""
    plane, url, session = control_plane
    plane.create_answer = answer
    with pytest.raises(expected) as caught:
        await ThalovantApi(session, _tokens(), api_url=url).create_connection(
            HUB, name="Home Assistant (Maison)", kind=CONNECTION_KIND
        )
    assert type(caught.value) is expected
    assert caught.value.status == answer[0]
    if expected is ThalovantAlreadyLinkedError:
        assert caught.value.connection_id == "c-old"


async def test_kind_not_echoed(
    control_plane: tuple[ControlPlane, str, ClientSession],
) -> None:
    """An API that ignores the kind: the SDK deletes the connection, we say unsupported."""
    plane, url, session = control_plane
    plane.echo_kind = False
    with pytest.raises(ThalovantUnsupportedError):
        await ThalovantApi(session, _tokens(), api_url=url).create_connection(
            HUB, name="n", kind=CONNECTION_KIND
        )
    assert plane.deleted == [(CLIENT, "etag-1")]


@pytest.mark.parametrize(
    ("status", "timeout", "expected"),
    [
        ("failed", 5, ThalovantAdmissionFailedError),
        ("applied", 0.01, ThalovantAdmissionTimeoutError),
    ],
)
async def test_admission_outcomes(
    control_plane: tuple[ControlPlane, str, ClientSession],
    status: str,
    timeout: float,
    expected: type[Exception],
) -> None:
    """A failed admission and one that runs out of time are told apart."""
    plane, url, session = control_plane
    plane.operation_status = status
    credentials = ConnectionCredentials(
        HUB, CLIENT, "n", "wss://maison.hubs.example", {"x": "y"}, "/v1/operations/op-1"
    )
    with pytest.raises(expected):
        await ThalovantApi(session, _tokens(), api_url=url).wait_for_admission(
            credentials, timeout=timeout
        )


async def test_nothing_to_admit(
    control_plane: tuple[ControlPlane, str, ClientSession],
) -> None:
    """Without an operation there is nothing to wait for."""
    _, url, session = control_plane
    credentials = ConnectionCredentials(HUB, CLIENT, "n", "wss://h", {"x": "y"}, None)
    await ThalovantApi(session, _tokens(), api_url=url).wait_for_admission(
        credentials, timeout=5
    )


async def test_unreachable_api() -> None:
    """A control plane nobody answers on is a connection error."""
    async with ClientSession() as session:
        with pytest.raises(ThalovantConnectionError):
            await ThalovantApi(
                session, _tokens(), api_url="http://127.0.0.1:9"
            ).get_account()


async def test_rejected_token(
    control_plane: tuple[ControlPlane, str, ClientSession],
) -> None:
    """A token the API does not know is an auth error."""
    _, url, session = control_plane
    with pytest.raises(ThalovantAuthError):
        await ThalovantApi(
            session, Tokens("wrong", None, (), None), api_url=url
        ).get_account()


def test_unusable_identity() -> None:
    """Stored credentials the SDK cannot read are a ValueError."""
    credentials = ConnectionCredentials(
        HUB, CLIENT, "n", "wss://h", {"site_id": "x"}, None
    )
    with pytest.raises(ValueError):
        HubConnection(None, credentials)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (thalovant.ThalovantHubRefusedError("refused"), ThalovantAuthError),
        (
            thalovant.ThalovantAdmissionTimeoutError("slow"),
            ThalovantAdmissionTimeoutError,
        ),
        (
            thalovant.ThalovantAdmissionFailedError("failed", error_code="x"),
            ThalovantAdmissionFailedError,
        ),
        (thalovant.ThalovantTimeoutError("slow hub"), ThalovantConnectionError),
        (thalovant.ThalovantConnectionError("dns"), ThalovantConnectionError),
        (
            thalovant.ThalovantDeviceLoginPending("wait", interval=7.5),
            DeviceLoginPending,
        ),
    ],
)
def test_sdk_errors_translate(error: Exception, expected: type[Exception]) -> None:
    """The SDK's own error classes land where the flow expects them."""
    translated = api._translate(error)
    assert type(translated) is expected


async def test_unreachable_hub(tmp_path: Path) -> None:
    """A hub nobody answers for is a connection error, and nothing is left running."""
    credentials = ConnectionCredentials(
        HUB,
        CLIENT,
        "n",
        "wss://127.0.0.1:9",
        {
            "access_key": "k",
            "password": "p",
            "site_id": "home-assistant",
            "default_master": "127.0.0.1",
            "default_port": 9,
            "data_plane_endpoints": {"wss": "wss://127.0.0.1:9"},
        },
        None,
    )
    async with ClientSession() as session:
        link = HubConnection(session, credentials, state_dir=str(tmp_path / "noise"))
        with pytest.raises(ThalovantConnectionError):
            await link.connect()
        assert link.connected is False
        await link.close()
