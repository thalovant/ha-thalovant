"""Tests for the adapter between the integration and the Thalovant SDK.

These drive api.py with a fake SDK that has thalovant 0.9.0's names and shapes
(see api.SDK_NAMES), so they need no SDK installed. test_api_sdk.py runs the
same adapter against the real SDK when it is installed.
"""

from collections.abc import Generator
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from custom_components.thalovant import api
from custom_components.thalovant.api import (
    Account,
    ConnectionCredentials,
    DeviceLogin,
    DeviceLoginDenied,
    DeviceLoginExpired,
    DeviceLoginPending,
    Hub,
    HubConnection,
    HubMessage,
    ThalovantAdmissionFailedError,
    ThalovantAdmissionTimeoutError,
    ThalovantAlreadyLinkedError,
    ThalovantApi,
    ThalovantApiError,
    ThalovantAuth,
    ThalovantAuthError,
    ThalovantConnectionError,
    ThalovantError,
    ThalovantPlanError,
    ThalovantUnsupportedError,
    Tokens,
)

from .conftest import CONNECTION_ID, HUB_ID, OTHER_HUB_ID


class SdkError(Exception):
    def __init__(self, message: str = "", **facts: Any) -> None:
        super().__init__(message)
        for key, value in facts.items():
            setattr(self, key, value)


class SdkIdentityError(SdkError):
    pass


class SdkConnectionError(SdkError):
    pass


class SdkTimeoutError(SdkError):
    pass


class SdkHubRefusedError(SdkConnectionError):
    pass


class SdkAdmissionTimeoutError(SdkConnectionError, SdkTimeoutError):
    pass


class SdkAdmissionFailedError(SdkConnectionError):
    pass


class SdkAPIError(SdkError):
    pass


class SdkAPIUnreachableError(SdkAPIError, SdkConnectionError):
    pass


class SdkAuthError(SdkAPIError):
    pass


class SdkPlanError(SdkAPIError):
    pass


class SdkAlreadyLinkedError(SdkAPIError):
    pass


class SdkUnsupportedError(SdkAPIError):
    pass


class SdkPending(SdkAPIError):
    pass


class SdkExpired(SdkAPIError):
    pass


class SdkDenied(SdkAPIError):
    pass


@dataclass
class SdkDeviceAuthorization:
    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str | None
    interval: float
    expires_in: int


@pytest.fixture
def sdk() -> Generator[SimpleNamespace]:
    """A fake thalovant 0.9.0, installed for one test."""
    fake = SimpleNamespace(
        AsyncThalovantControlPlane=MagicMock(),
        AsyncHubSession=MagicMock(),
        ThalovantIdentity=MagicMock(),
        DeviceAuthorization=SdkDeviceAuthorization,
        hub_display_name=lambda hub: f"display:{hub['name']}",
        ThalovantError=SdkError,
        ThalovantAPIError=SdkAPIError,
        ThalovantAPIUnreachableError=SdkAPIUnreachableError,
        ThalovantAuthError=SdkAuthError,
        ThalovantPlanError=SdkPlanError,
        ThalovantAlreadyLinkedError=SdkAlreadyLinkedError,
        ThalovantUnsupportedConnectionTypeError=SdkUnsupportedError,
        ThalovantConnectionError=SdkConnectionError,
        ThalovantHubRefusedError=SdkHubRefusedError,
        ThalovantTimeoutError=SdkTimeoutError,
        ThalovantAdmissionTimeoutError=SdkAdmissionTimeoutError,
        ThalovantAdmissionFailedError=SdkAdmissionFailedError,
        ThalovantIdentityError=SdkIdentityError,
        ThalovantDeviceLoginPending=SdkPending,
        ThalovantDeviceLoginExpired=SdkExpired,
        ThalovantDeviceLoginDenied=SdkDenied,
    )
    assert set(vars(fake)) == set(api.SDK_NAMES)
    with patch.object(api, "_sdk_module", fake):
        yield fake


def _tokens() -> Tokens:
    return Tokens(
        access_token="tok",
        expires_at=datetime(2027, 9, 27, tzinfo=UTC),
        scopes=("hubs:read",),
        token_id="t1",
    )


def _credentials(
    operation_url: str | None = "/v1/operations/op-1",
) -> ConnectionCredentials:
    return ConnectionCredentials(
        hub_id=HUB_ID,
        connection_id=CONNECTION_ID,
        name="Home Assistant (Maison)",
        endpoint="wss://hub.example",
        secret={"access_key": "k", "password": "p", "default_port": 443},
        operation_url=operation_url,
    )


def test_load_sdk() -> None:
    """The SDK is imported by name, and its absence is not an import error."""
    module = object()
    with patch.object(api.importlib, "import_module", return_value=module) as load:
        assert api._load_sdk() is module
    load.assert_called_once_with("thalovant")
    with patch.object(api.importlib, "import_module", side_effect=ImportError):
        assert api._load_sdk() is None


async def test_sdk_not_installed() -> None:
    """Without the SDK every call is a clear ThalovantError."""
    with (
        patch.object(api, "_sdk_module", None),
        pytest.raises(ThalovantError, match="not installed"),
    ):
        await ThalovantAuth(MagicMock()).start_device_login(client_name="x", scopes=[])


async def test_sdk_missing_a_name(sdk: SimpleNamespace) -> None:
    """An SDK without a name the adapter needs says which one."""
    del sdk.AsyncThalovantControlPlane
    with pytest.raises(ThalovantError, match="has no AsyncThalovantControlPlane"):
        await ThalovantApi(MagicMock(), _tokens()).get_account()


async def test_device_login(sdk: SimpleNamespace) -> None:
    """Start and poll go to one control plane and come back as our types."""
    session = MagicMock()
    grant = SdkDeviceAuthorization(
        "dc", "WXYZ-2345", "https://v", "https://v?c", 5.0, 900
    )
    plane = sdk.AsyncThalovantControlPlane.return_value
    plane.begin_device_login = AsyncMock(return_value=grant)
    plane.poll_device_login = AsyncMock(
        return_value=SimpleNamespace(
            access_token="tok",
            expires_at=datetime(2027, 9, 27, tzinfo=UTC),
            scopes=["hubs:read"],
            token_id="t1",
        )
    )

    auth = ThalovantAuth(session)
    login = await auth.start_device_login(client_name="HA", scopes=("hubs:read",))
    assert login == DeviceLogin("dc", "WXYZ-2345", "https://v", "https://v?c", 5.0, 900)
    assert login.sdk is grant
    plane.begin_device_login.assert_awaited_once_with(
        scopes=["hubs:read"], client_name="HA"
    )

    assert await auth.poll_device_login(login) == _tokens()
    plane.poll_device_login.assert_awaited_once_with(grant)
    # One plane for both calls: it remembers each slow_down.
    sdk.AsyncThalovantControlPlane.assert_called_once_with(
        access_token=None, session=session
    )


async def test_api_url(sdk: SimpleNamespace) -> None:
    """A control plane other than production is passed through."""
    plane = sdk.AsyncThalovantControlPlane.return_value
    plane.begin_device_login = AsyncMock(
        return_value=SdkDeviceAuthorization("dc", "c", "u", None, 5, 900)
    )
    session = MagicMock()
    await ThalovantAuth(session, api_url="http://127.0.0.1:1").start_device_login(
        client_name="HA", scopes=()
    )
    sdk.AsyncThalovantControlPlane.assert_called_once_with(
        "http://127.0.0.1:1", access_token=None, session=session
    )


async def test_poll_without_sdk_login(sdk: SimpleNamespace) -> None:
    """A login made elsewhere is rebuilt as the SDK's DeviceAuthorization."""
    plane = sdk.AsyncThalovantControlPlane.return_value
    plane.poll_device_login = AsyncMock(
        return_value=SimpleNamespace(
            access_token="tok", expires_at=None, scopes=(), token_id=None
        )
    )
    login = DeviceLogin("dc", "WXYZ-2345", "https://v", None, 5.0, 900)
    tokens = await ThalovantAuth(MagicMock()).poll_device_login(login)
    assert tokens == Tokens("tok", None, (), None)
    [grant] = plane.poll_device_login.await_args.args
    assert asdict(grant) == {
        "device_code": "dc",
        "user_code": "WXYZ-2345",
        "verification_uri": "https://v",
        "verification_uri_complete": None,
        "interval": 5.0,
        "expires_in": 900,
    }


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (SdkPending("wait", interval=10.0, status_code=400), DeviceLoginPending),
        (SdkExpired("gone", status_code=400), DeviceLoginExpired),
        (SdkDenied("no", status_code=400), DeviceLoginDenied),
    ],
)
async def test_device_login_outcomes(
    sdk: SimpleNamespace, raised: Exception, expected: type[ThalovantError]
) -> None:
    """The SDK's device-login outcomes become ours, before the API errors they are."""
    sdk.AsyncThalovantControlPlane.return_value.poll_device_login = AsyncMock(
        side_effect=raised
    )
    login = DeviceLogin("dc", "c", "u", None, 5, 900, sdk=object())
    with pytest.raises(ThalovantError) as caught:
        await ThalovantAuth(MagicMock()).poll_device_login(login)
    assert type(caught.value) is expected
    assert caught.value.__cause__ is raised
    if expected is DeviceLoginPending:
        assert caught.value.interval == 10.0


async def test_api_calls(sdk: SimpleNamespace) -> None:
    """Every call goes to one control plane made from the stored token."""
    session = MagicMock()
    plane = sdk.AsyncThalovantControlPlane.return_value
    plane.get_profile = AsyncMock(
        return_value={"id": "a1", "display_name": " G ", "email": 7}
    )
    plane.create_client_identity = AsyncMock(
        return_value=SimpleNamespace(
            client_id=CONNECTION_ID,
            identity=MagicMock(default_master="maison.example"),
            endpoint=SimpleNamespace(protocol="wss", endpoint="wss://hub.example"),
            operation=SimpleNamespace(id="op-1", links={"self": "/v1/operations/op-1"}),
        )
    )
    identity = plane.create_client_identity.return_value.identity
    identity.as_dict.return_value = {
        "access_key": "k",
        "password": "p",
        "default_port": 443,
    }
    plane.wait_for_admission = AsyncMock()
    plane.delete_client = AsyncMock()
    plane.revoke_api_token = AsyncMock()

    thalovant = ThalovantApi(session, _tokens())
    assert await thalovant.get_account() == Account("a1", "G", None)
    credentials = await thalovant.create_connection(
        HUB_ID, name="Home Assistant (Maison)", kind="home_assistant"
    )
    assert credentials == _credentials()
    plane.create_client_identity.assert_awaited_once_with(
        HUB_ID, name="Home Assistant (Maison)", connection_type="home_assistant"
    )
    identity.as_dict.assert_called_once_with(include_secrets=True)
    await thalovant.wait_for_admission(credentials, timeout=180)
    plane.wait_for_admission.assert_awaited_once_with(
        "/v1/operations/op-1", timeout=180
    )
    await thalovant.delete_connection(CONNECTION_ID)
    plane.delete_client.assert_awaited_once_with(CONNECTION_ID)
    await thalovant.revoke_token()
    plane.revoke_api_token.assert_awaited_once_with("t1")

    sdk.AsyncThalovantControlPlane.assert_called_once_with(
        access_token="tok", session=session
    )


async def test_create_connection_fallbacks(sdk: SimpleNamespace) -> None:
    """No selected endpoint or operation link: the identity's host, the operation id."""
    plane = sdk.AsyncThalovantControlPlane.return_value
    result = SimpleNamespace(
        client_id=CONNECTION_ID,
        identity=MagicMock(default_master="maison.example"),
        endpoint=None,
        operation=SimpleNamespace(id="op-9", links={}),
    )
    result.identity.as_dict.return_value = {"access_key": "k"}
    plane.create_client_identity = AsyncMock(return_value=result)
    credentials = await ThalovantApi(MagicMock(), _tokens()).create_connection(
        HUB_ID, name="n", kind="home_assistant"
    )
    assert credentials.endpoint == "maison.example"
    assert credentials.operation_url == "op-9"

    result.operation = None
    credentials = await ThalovantApi(MagicMock(), _tokens()).create_connection(
        HUB_ID, name="n", kind="home_assistant"
    )
    assert credentials.operation_url is None

    result.client_id = None
    with pytest.raises(ThalovantApiError, match="without an id"):
        await ThalovantApi(MagicMock(), _tokens()).create_connection(
            HUB_ID, name="n", kind="home_assistant"
        )


async def test_account_without_id(sdk: SimpleNamespace) -> None:
    """A profile without an id is an API error, not an account."""
    sdk.AsyncThalovantControlPlane.return_value.get_profile = AsyncMock(
        return_value={"email": "x@example.com"}
    )
    with pytest.raises(ThalovantApiError, match="no account id"):
        await ThalovantApi(MagicMock(), _tokens()).get_account()


async def test_revoke_without_token_id(sdk: SimpleNamespace) -> None:
    """A token stored without its id cannot be revoked here, and says so."""
    tokens = Tokens("tok", None, (), None)
    with pytest.raises(ThalovantApiError, match="no id"):
        await ThalovantApi(MagicMock(), tokens).revoke_token()
    sdk.AsyncThalovantControlPlane.assert_not_called()


async def test_list_hubs(sdk: SimpleNamespace) -> None:
    """Own hubs by owner over every page, locked ones left out, then public ones."""
    plane = sdk.AsyncThalovantControlPlane.return_value
    plane.get_profile = AsyncMock(return_value={"id": "a1"})
    plane.list_hubs = AsyncMock(
        side_effect=[
            {
                "data": [
                    {"id": HUB_ID, "name": "maison"},
                    {"id": "locked", "name": "old", "is_locked": True},
                    "not a hub",
                ],
                "meta": {"next": "c2"},
            },
            {"data": [{"id": "", "name": "no id"}], "meta": {"next": None}},
        ]
    )
    plane.list_public_hubs = AsyncMock(
        return_value={
            "data": [
                {"id": OTHER_HUB_ID, "name": "daily-desk", "title": "Daily Desk"},
                {"id": HUB_ID, "name": "maison", "title": "Maison (public)"},
                {"id": "untitled", "name": "story-time"},
                {"name": "no id either"},
            ],
            "meta": {},
        }
    )

    hubs = await ThalovantApi(MagicMock(), _tokens()).list_hubs()
    assert hubs == [
        Hub(HUB_ID, "display:maison"),
        Hub(OTHER_HUB_ID, "Daily Desk"),
        Hub("untitled", "display:story-time"),
    ]
    assert plane.list_hubs.await_args_list == [
        call(owner_id="a1", cursor=None),
        call(owner_id="a1", cursor="c2"),
    ]
    plane.list_public_hubs.assert_awaited_once_with(cursor=None)


async def test_list_hubs_stops_paging(sdk: SimpleNamespace) -> None:
    """A listing that never ends is read up to MAX_PAGES pages."""
    plane = sdk.AsyncThalovantControlPlane.return_value
    plane.get_profile = AsyncMock(return_value={"id": "a1"})
    plane.list_hubs = AsyncMock(return_value={"data": None, "meta": {"next": "again"}})
    plane.list_public_hubs = AsyncMock(return_value={"meta": "odd"})
    thalovant = ThalovantApi(MagicMock(), _tokens())
    await thalovant.get_account()
    assert await thalovant.list_hubs() == []
    assert plane.list_hubs.await_count == api.MAX_PAGES
    # The account id is remembered, not asked for again.
    plane.get_profile.assert_awaited_once()


@pytest.mark.parametrize(
    ("raised", "expected", "facts"),
    [
        (SdkAuthError("401", status_code=401), ThalovantAuthError, {"status": 401}),
        (
            SdkPlanError("402", status_code=402, code=None, detail="Upgrade"),
            ThalovantPlanError,
            {"status": 402, "detail": "Upgrade"},
        ),
        (
            SdkAlreadyLinkedError(
                "409",
                status_code=409,
                code="home_assistant_already_linked",
                client_id="c-old",
            ),
            ThalovantAlreadyLinkedError,
            {"code": "home_assistant_already_linked", "connection_id": "c-old"},
        ),
        (
            SdkUnsupportedError("422", status_code=422),
            ThalovantUnsupportedError,
            {"status": 422},
        ),
        (SdkAPIError("400", status_code=400), ThalovantApiError, {"status": 400}),
        (
            SdkAPIUnreachableError("unreachable"),
            ThalovantConnectionError,
            {"status": None},
        ),
        # A local refusal (no token, odd answer) is not a network failure.
        (SdkAPIError("Missing token"), ThalovantApiError, {"status": None}),
        (
            SdkAPIError("busy", status_code=429),
            ThalovantConnectionError,
            {"status": 429},
        ),
        (
            SdkAPIError("down", status_code=503),
            ThalovantConnectionError,
            {"status": 503},
        ),
        (SdkHubRefusedError("refused"), ThalovantAuthError, {"status": None}),
        (SdkAdmissionTimeoutError("slow"), ThalovantAdmissionTimeoutError, {}),
        (
            SdkAdmissionFailedError("failed", error_code="op_failed"),
            ThalovantAdmissionFailedError,
            {"code": "op_failed"},
        ),
        (SdkConnectionError("dns"), ThalovantConnectionError, {}),
        (SdkTimeoutError("slow hub"), ThalovantConnectionError, {}),
        (SdkIdentityError("odd"), ThalovantError, {"status": None}),
    ],
)
async def test_errors(
    sdk: SimpleNamespace,
    raised: Exception,
    expected: type[ThalovantError],
    facts: dict[str, Any],
) -> None:
    """SDK errors become ours, most specific first, with what the API said."""
    sdk.AsyncThalovantControlPlane.return_value.delete_client = AsyncMock(
        side_effect=raised
    )
    with pytest.raises(ThalovantError) as caught:
        await ThalovantApi(MagicMock(), _tokens()).delete_connection(CONNECTION_ID)
    assert type(caught.value) is expected
    assert str(caught.value) == str(raised)
    assert caught.value.__cause__ is raised
    for key, value in facts.items():
        assert getattr(caught.value, key) == value


async def test_other_errors_pass_through(sdk: SimpleNamespace) -> None:
    """Anything that is not an SDK error is left as it is."""
    sdk.AsyncThalovantControlPlane.return_value.delete_client = AsyncMock(
        side_effect=KeyError("x")
    )
    with pytest.raises(KeyError):
        await ThalovantApi(MagicMock(), _tokens()).delete_connection(CONNECTION_ID)


async def test_hub_connection(sdk: SimpleNamespace) -> None:
    """The link wraps one SDK session and hands events over as our messages."""
    session = MagicMock()
    link = sdk.AsyncHubSession.for_identity.return_value
    link.connected = 1
    link.connect = AsyncMock()
    link.run = AsyncMock()
    link.close = AsyncMock()
    link.reply = AsyncMock()
    link.on_state_change = MagicMock(return_value="unsub-state")
    link.on = MagicMock(return_value="unsub-message")

    connection = HubConnection(session, _credentials(), state_dir="/config/.storage/x")
    sdk.ThalovantIdentity.from_mapping.assert_called_once_with(_credentials().secret)
    sdk.AsyncHubSession.for_identity.assert_called_once_with(
        sdk.ThalovantIdentity.from_mapping.return_value,
        session=session,
        noise_state_dir="/config/.storage/x",
    )
    assert connection.connected is True

    await connection.connect()
    await connection.run()
    await connection.close()
    link.connect.assert_awaited_once()
    link.run.assert_awaited_once()
    link.close.assert_awaited_once()

    def on_state(_: bool) -> None:
        pass

    assert connection.on_state_change(on_state) == "unsub-state"
    link.on_state_change.assert_called_once_with(on_state)

    received: list[HubMessage] = []
    assert connection.on_message("thalovant.home.request", received.append) == (
        "unsub-message"
    )
    event_name, relay = link.on.call_args.args
    assert event_name == "thalovant.home.request"
    event = SimpleNamespace(
        name="thalovant.home.request", data={"request_id": "r1"}, context={"s": 1}
    )
    assert relay(event) is None
    [message] = received
    assert message == HubMessage(
        "thalovant.home.request", {"request_id": "r1"}, {"s": 1}
    )
    assert message.sdk is event

    await connection.reply(message, "thalovant.home.response", {"speech": "ok"})
    link.reply.assert_awaited_once_with(
        event, "thalovant.home.response", {"speech": "ok"}
    )


async def test_hub_connection_errors(sdk: SimpleNamespace) -> None:
    """A refused hub is an auth error; an unreachable one a connection error."""
    link = sdk.AsyncHubSession.for_identity.return_value
    link.connect = AsyncMock(side_effect=SdkHubRefusedError("refused"))
    link.run = AsyncMock(side_effect=SdkConnectionError("gone"))
    connection = HubConnection(MagicMock(), _credentials())
    with pytest.raises(ThalovantAuthError):
        await connection.connect()
    with pytest.raises(ThalovantConnectionError):
        await connection.run()


def test_hub_connection_bad_identity(sdk: SimpleNamespace) -> None:
    """Credentials the SDK cannot read are a ValueError; other failures pass."""
    sdk.ThalovantIdentity.from_mapping.side_effect = SdkIdentityError("no password")
    with pytest.raises(ValueError, match="unusable"):
        HubConnection(MagicMock(), _credentials())
    sdk.ThalovantIdentity.from_mapping.side_effect = RuntimeError("bug")
    with pytest.raises(RuntimeError):
        HubConnection(MagicMock(), _credentials())


def test_tokens_round_trip() -> None:
    """Tokens survive storage, and their repr keeps the token out."""
    tokens = _tokens()
    assert Tokens.from_dict(tokens.to_dict()) == tokens
    assert "tok'" not in repr(tokens)
    no_expiry = Tokens("t", None, (), None)
    assert Tokens.from_dict(no_expiry.to_dict()) == no_expiry
    # Entries written before token_id existed still read.
    assert Tokens.from_dict(
        {"access_token": "t", "refresh_token": None, "scopes": []}
    ) == Tokens("t", None, (), None)


@pytest.mark.parametrize(
    "data",
    [
        None,
        {},
        {"access_token": ""},
        {"access_token": "t", "scopes": "hubs:read"},
        {"access_token": "t", "scopes": [1]},
        {"access_token": "t", "token_id": 5},
        {"access_token": "t", "expires_at": "not a date"},
    ],
)
def test_tokens_bad_data(data: Any) -> None:
    """Unreadable tokens raise ValueError."""
    with pytest.raises(ValueError):
        Tokens.from_dict(data)


def test_credentials_round_trip() -> None:
    """Credentials survive storage, with the secret frozen and out of repr."""
    credentials = _credentials()
    assert ConnectionCredentials.from_dict(credentials.to_dict()) == credentials
    assert "'p'" not in repr(credentials)
    with pytest.raises(TypeError):
        credentials.secret["password"] = "q"  # type: ignore[index]


@pytest.mark.parametrize(
    "change",
    [
        {"secret": None},
        {"secret": {}},
        {"hub_id": None},
        {"endpoint": ""},
        {"operation_url": 3},
    ],
)
def test_credentials_bad_data(change: dict[str, Any]) -> None:
    """Unreadable credentials raise ValueError."""
    with pytest.raises(ValueError):
        ConnectionCredentials.from_dict({**_credentials().to_dict(), **change})
    with pytest.raises(ValueError):
        ConnectionCredentials.from_dict("not a mapping")  # type: ignore[arg-type]
