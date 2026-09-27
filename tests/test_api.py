"""Tests for the adapter between the integration and the Thalovant SDK.

The SDK's async API is still being settled, so these tests drive api.py with a
fake SDK that has the contract's names and shapes (see api.SDK_NAMES). When the
SDK lands, this file and api.py are the ones to update.
"""

from collections.abc import Generator
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

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

from .conftest import CONNECTION_ID, HUB_ID


class SdkError(Exception):
    def __init__(self, message: str = "", **facts: Any) -> None:
        super().__init__(message)
        for key, value in facts.items():
            setattr(self, key, value)


class SdkAuthError(SdkError):
    pass


class SdkConnectionError(SdkError):
    pass


class SdkApiError(SdkError):
    pass


class SdkPlanError(SdkApiError):
    pass


class SdkAlreadyLinkedError(SdkApiError):
    pass


class SdkUnsupportedError(SdkApiError):
    pass


class SdkPending(SdkError):
    pass


class SdkExpired(SdkError):
    pass


class SdkDenied(SdkError):
    pass


@dataclass
class SdkDeviceLogin:
    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str | None
    interval: int
    expires_in: int


class SdkDict:
    """An SDK model that round-trips through to_dict()/from_dict()."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data

    def to_dict(self) -> dict[str, Any]:
        return dict(self.data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SdkDict:
        return cls(dict(data))


@pytest.fixture
def sdk() -> Generator[SimpleNamespace]:
    """A fake SDK with the names api.py takes, installed for one test."""
    fake = SimpleNamespace(
        ThalovantAuth=MagicMock(),
        ThalovantApi=MagicMock(),
        HubConnection=MagicMock(),
        DeviceLogin=SdkDeviceLogin,
        Tokens=SdkDict,
        ConnectionCredentials=SdkDict,
        ThalovantError=SdkError,
        ThalovantAuthError=SdkAuthError,
        ThalovantConnectionError=SdkConnectionError,
        ThalovantApiError=SdkApiError,
        ThalovantPlanError=SdkPlanError,
        ThalovantAlreadyLinkedError=SdkAlreadyLinkedError,
        ThalovantUnsupportedError=SdkUnsupportedError,
        DeviceLoginPending=SdkPending,
        DeviceLoginExpired=SdkExpired,
        DeviceLoginDenied=SdkDenied,
    )
    assert set(vars(fake)) == set(api.SDK_NAMES)
    with patch.object(api, "_sdk_module", fake):
        yield fake


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
    del sdk.ThalovantApi
    with pytest.raises(ThalovantError, match="has no ThalovantApi"):
        await ThalovantApi(MagicMock(), _tokens()).get_account()


def _tokens() -> Tokens:
    return Tokens(
        access_token="tok",
        refresh_token=None,
        expires_at=datetime(2027, 9, 27, tzinfo=UTC),
        scopes=("hubs:read",),
    )


def _credentials() -> ConnectionCredentials:
    return ConnectionCredentials(
        hub_id=HUB_ID,
        connection_id=CONNECTION_ID,
        name="Home Assistant (Maison)",
        endpoint="wss://hub.example/ws",
        secret={"password": "p"},
        operation_url="https://api.example/v1/operations/1",
    )


async def test_device_login(sdk: SimpleNamespace) -> None:
    """Start and poll go to one SDK auth client and come back as our types."""
    session = MagicMock()
    sdk_login = SdkDeviceLogin("dc", "WXYZ-2345", "https://v", "https://v?c", 5, 900)
    client = sdk.ThalovantAuth.return_value
    client.start_device_login = AsyncMock(return_value=sdk_login)
    client.poll_device_login = AsyncMock(return_value=SdkDict(_tokens().to_dict()))

    auth = ThalovantAuth(session)
    login = await auth.start_device_login(client_name="HA", scopes=("hubs:read",))
    assert login == DeviceLogin("dc", "WXYZ-2345", "https://v", "https://v?c", 5, 900)
    assert login.sdk is sdk_login
    client.start_device_login.assert_awaited_once_with(
        client_name="HA", scopes=["hubs:read"]
    )

    assert await auth.poll_device_login(login) == _tokens()
    client.poll_device_login.assert_awaited_once_with(sdk_login)
    sdk.ThalovantAuth.assert_called_once_with(session)


async def test_poll_without_sdk_login(sdk: SimpleNamespace) -> None:
    """A login made elsewhere is rebuilt as the SDK's own type."""
    client = sdk.ThalovantAuth.return_value
    client.poll_device_login = AsyncMock(return_value=SdkDict(_tokens().to_dict()))
    login = DeviceLogin("dc", "WXYZ-2345", "https://v", None, 5, 900)
    await ThalovantAuth(MagicMock()).poll_device_login(login)
    [sdk_login] = client.poll_device_login.await_args.args
    assert asdict(sdk_login) == {
        "device_code": "dc",
        "user_code": "WXYZ-2345",
        "verification_uri": "https://v",
        "verification_uri_complete": None,
        "interval": 5,
        "expires_in": 900,
    }


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (SdkPending("wait", interval=10), DeviceLoginPending),
        (SdkExpired("gone"), DeviceLoginExpired),
        (SdkDenied("no"), DeviceLoginDenied),
    ],
)
async def test_device_login_errors(
    sdk: SimpleNamespace, raised: Exception, expected: type[ThalovantError]
) -> None:
    """The SDK's device-login outcomes become ours."""
    sdk.ThalovantAuth.return_value.poll_device_login = AsyncMock(side_effect=raised)
    login = DeviceLogin("dc", "c", "u", None, 5, 900, sdk=object())
    with pytest.raises(expected) as caught:
        await ThalovantAuth(MagicMock()).poll_device_login(login)
    assert caught.value.__cause__ is raised
    if expected is DeviceLoginPending:
        assert caught.value.interval == 10


async def test_pending_without_interval(sdk: SimpleNamespace) -> None:
    """A pending error without an interval says 0 and lets the flow decide."""
    sdk.ThalovantAuth.return_value.poll_device_login = AsyncMock(
        side_effect=SdkPending()
    )
    with pytest.raises(DeviceLoginPending) as caught:
        await ThalovantAuth(MagicMock()).poll_device_login(
            DeviceLogin("dc", "c", "u", None, 5, 900, sdk=object())
        )
    assert caught.value.interval == 0


async def test_api_calls(sdk: SimpleNamespace) -> None:
    """Every API call goes to one SDK client made from the stored token."""
    session = MagicMock()
    client = sdk.ThalovantApi.return_value
    client.get_account = AsyncMock(
        return_value=SimpleNamespace(id="a1", display_name="G", email=None)
    )
    client.list_hubs = AsyncMock(
        return_value=[
            SimpleNamespace(id=HUB_ID, name="Maison", public=0, languages=["fr-FR"])
        ]
    )
    client.create_connection = AsyncMock(return_value=SdkDict(_credentials().to_dict()))
    client.wait_for_admission = AsyncMock()
    client.delete_connection = AsyncMock()

    thalovant = ThalovantApi(session, _tokens())
    assert await thalovant.get_account() == Account("a1", "G", None)
    assert await thalovant.list_hubs() == [Hub(HUB_ID, "Maison", False, ("fr-FR",))]
    credentials = await thalovant.create_connection(
        HUB_ID, name="Home Assistant (Maison)", kind="home_assistant"
    )
    assert credentials == _credentials()
    client.create_connection.assert_awaited_once_with(
        HUB_ID, name="Home Assistant (Maison)", kind="home_assistant"
    )
    await thalovant.wait_for_admission(credentials, timeout=180)
    [sdk_credentials] = client.wait_for_admission.await_args.args
    assert sdk_credentials.data == _credentials().to_dict()
    assert client.wait_for_admission.await_args.kwargs == {"timeout": 180}
    await thalovant.delete_connection(CONNECTION_ID)
    client.delete_connection.assert_awaited_once_with(CONNECTION_ID)

    sdk.ThalovantApi.assert_called_once()
    called_session, sdk_tokens = sdk.ThalovantApi.call_args.args
    assert called_session is session
    assert sdk_tokens.data == _tokens().to_dict()


@pytest.mark.parametrize(
    ("raised", "expected", "facts"),
    [
        (SdkAuthError("401", status=401), ThalovantAuthError, {"status": 401}),
        (SdkConnectionError("503", status=503), ThalovantConnectionError, {}),
        (
            SdkPlanError("402", status=402, code=None, detail="Upgrade"),
            ThalovantPlanError,
            {"status": 402, "detail": "Upgrade"},
        ),
        (
            SdkAlreadyLinkedError(
                "409",
                status=409,
                code="home_assistant_already_linked",
                connection_id="c-old",
            ),
            ThalovantAlreadyLinkedError,
            {"code": "home_assistant_already_linked", "connection_id": "c-old"},
        ),
        (SdkUnsupportedError("422", status=422), ThalovantUnsupportedError, {}),
        (SdkApiError("400", status=400), ThalovantApiError, {"status": 400}),
        (SdkError("odd"), ThalovantError, {"status": None}),
    ],
)
async def test_api_errors(
    sdk: SimpleNamespace,
    raised: Exception,
    expected: type[ThalovantError],
    facts: dict[str, Any],
) -> None:
    """SDK errors become ours, most specific first, with what the API said."""
    sdk.ThalovantApi.return_value.create_connection = AsyncMock(side_effect=raised)
    with pytest.raises(ThalovantError) as caught:
        await ThalovantApi(MagicMock(), _tokens()).create_connection(
            HUB_ID, name="n", kind="home_assistant"
        )
    assert type(caught.value) is expected
    assert str(caught.value) == str(raised)
    assert caught.value.__cause__ is raised
    for key, value in facts.items():
        assert getattr(caught.value, key) == value


async def test_other_errors_pass_through(sdk: SimpleNamespace) -> None:
    """Anything that is not an SDK error is left as it is."""
    sdk.ThalovantApi.return_value.delete_connection = AsyncMock(
        side_effect=TimeoutError
    )
    with pytest.raises(TimeoutError):
        await ThalovantApi(MagicMock(), _tokens()).delete_connection(CONNECTION_ID)


async def test_hub_connection(sdk: SimpleNamespace) -> None:
    """The link wraps one SDK connection and hands messages over as ours."""
    session = MagicMock()
    link = sdk.HubConnection.return_value
    link.connected = 1
    link.connect = AsyncMock()
    link.run = AsyncMock()
    link.close = AsyncMock()
    link.reply = AsyncMock()
    link.on_state_change = MagicMock(return_value="unsub-state")
    link.on_message = MagicMock(return_value="unsub-message")

    connection = HubConnection(session, _credentials())
    called_session, sdk_credentials = sdk.HubConnection.call_args.args
    assert called_session is session
    assert sdk_credentials.data == _credentials().to_dict()
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

    def on_request(message: HubMessage) -> None:
        received.append(message)

    assert connection.on_message("thalovant.home.request", on_request) == (
        "unsub-message"
    )
    msg_type, relay = link.on_message.call_args.args
    assert msg_type == "thalovant.home.request"
    sdk_message = SimpleNamespace(
        type="thalovant.home.request", data={"request_id": "r1"}, context={"s": 1}
    )
    assert relay(sdk_message) is None
    [message] = received
    assert message == HubMessage(
        "thalovant.home.request", {"request_id": "r1"}, {"s": 1}
    )
    assert message.sdk is sdk_message

    await connection.reply(message, "thalovant.home.response", {"speech": "ok"})
    link.reply.assert_awaited_once_with(
        sdk_message, "thalovant.home.response", {"speech": "ok"}
    )


async def test_hub_connection_errors(sdk: SimpleNamespace) -> None:
    """A refused or unreachable hub raises our errors."""
    link = sdk.HubConnection.return_value
    link.connect = AsyncMock(side_effect=SdkAuthError("refused"))
    link.run = AsyncMock(side_effect=SdkConnectionError("gone"))
    connection = HubConnection(MagicMock(), _credentials())
    with pytest.raises(ThalovantAuthError):
        await connection.connect()
    with pytest.raises(ThalovantConnectionError):
        await connection.run()


def test_tokens_round_trip() -> None:
    """Tokens survive storage, and their repr keeps the token out."""
    tokens = _tokens()
    assert Tokens.from_dict(tokens.to_dict()) == tokens
    assert "tok" not in repr(tokens)
    no_expiry = Tokens("t", "r", None, ())
    assert Tokens.from_dict(no_expiry.to_dict()) == no_expiry


@pytest.mark.parametrize(
    "data",
    [
        None,
        {},
        {"access_token": ""},
        {"access_token": "t", "scopes": "hubs:read"},
        {"access_token": "t", "scopes": [1]},
        {"access_token": "t", "refresh_token": 5},
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
        {"secret": {"password": 1}},
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
