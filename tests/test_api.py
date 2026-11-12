"""Tests for the adapter between the integration and the Thalovant SDK.

These drive api.py with a fake SDK that has thalovant 0.12.0's names and shapes
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
    ThalovantClientKeyRejectedError,
    ThalovantConnectionError,
    ThalovantError,
    ThalovantHubKeyChangedError,
    ThalovantPlanError,
    ThalovantRateLimitedError,
    ThalovantUnsupportedError,
    Tokens,
    plain_speech,
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


class SdkClientKeyRejectedError(SdkHubRefusedError):
    pass


class SdkHubKeyChangedError(SdkConnectionError):
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


class SdkIntercomDisabledError(SdkAPIError):
    pass


class SdkIntercomUnavailableError(SdkIntercomDisabledError):
    pass


class SdkIntercomPlatformDisabledError(SdkIntercomDisabledError):
    pass


class SdkIntercomNotConfiguredError(SdkAPIError):
    pass


class SdkUrgentScopeRequiredError(SdkAuthError):
    pass


class SdkHubUnreachableError(SdkAPIError):
    pass


class SdkRateLimitedError(SdkAPIError):
    pass


class SdkUrgentBusyError(SdkRateLimitedError):
    pass


class SdkSkillNotInstalledError(SdkAPIError):
    pass


class SdkNotASpeakerError(SdkAPIError):
    pass


class SdkTooManyTargetsError(SdkAPIError):
    pass


class SdkHubLockedError(SdkAPIError):
    pass


class SdkNotCancellableError(SdkAPIError):
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
    """A fake thalovant 0.12.0, installed for one test."""
    fake = SimpleNamespace(
        AsyncThalovantControlPlane=MagicMock(),
        AsyncHubSession=MagicMock(),
        ThalovantIdentity=MagicMock(),
        DeviceAuthorization=SdkDeviceAuthorization,
        HOME_ASSISTANT_CLIENT_ID="thalovant-home-assistant",
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
        ThalovantClientKeyRejectedError=SdkClientKeyRejectedError,
        ThalovantHubKeyChangedError=SdkHubKeyChangedError,
        ThalovantTimeoutError=SdkTimeoutError,
        ThalovantAdmissionTimeoutError=SdkAdmissionTimeoutError,
        ThalovantAdmissionFailedError=SdkAdmissionFailedError,
        ThalovantIdentityError=SdkIdentityError,
        ThalovantDeviceLoginPending=SdkPending,
        ThalovantDeviceLoginExpired=SdkExpired,
        ThalovantDeviceLoginDenied=SdkDenied,
        ThalovantIntercomDisabledError=SdkIntercomDisabledError,
        ThalovantIntercomUnavailableError=SdkIntercomUnavailableError,
        ThalovantIntercomPlatformDisabledError=SdkIntercomPlatformDisabledError,
        ThalovantIntercomNotConfiguredError=SdkIntercomNotConfiguredError,
        ThalovantUrgentScopeRequiredError=SdkUrgentScopeRequiredError,
        ThalovantUrgentBusyError=SdkUrgentBusyError,
        ThalovantSkillNotInstalledError=SdkSkillNotInstalledError,
        ThalovantNotASpeakerError=SdkNotASpeakerError,
        ThalovantTooManyTargetsError=SdkTooManyTargetsError,
        ThalovantHubLockedError=SdkHubLockedError,
        ThalovantHubUnreachableError=SdkHubUnreachableError,
        ThalovantRateLimitedError=SdkRateLimitedError,
        ThalovantNotCancellableError=SdkNotCancellableError,
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


def test_plain_speech_needs_the_sdk() -> None:
    """Speech goes through the SDK's rules; without the SDK that is an error."""
    with (
        patch.object(api, "_sdk_module", None),
        pytest.raises(ThalovantError, match="not installed"),
    ):
        plain_speech("Hello")


def test_hub_message_arrival() -> None:
    """A message records when it arrived, on the monotonic clock."""
    before = api.time.monotonic()
    message = HubMessage("t", {}, {})
    assert before <= message.received_at <= api.time.monotonic()


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
    # As the registered app: the approval page vouches for the name.
    plane.begin_device_login.assert_awaited_once_with(
        scopes=["hubs:read"], client_name="HA", client_id="thalovant-home-assistant"
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
    # The plane knows its token's id, so revoking a dead token is not an error.
    assert plane.token_id == "t1"
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


async def test_list_hubs_reads_home_assistant_capability(
    sdk: SimpleNamespace,
) -> None:
    """capabilities.home_assistant says whether a hub can link; anything else is unknown."""
    plane = sdk.AsyncThalovantControlPlane.return_value
    plane.get_profile = AsyncMock(return_value={"id": "a1"})
    plane.list_hubs = AsyncMock(
        return_value={
            "data": [
                {"id": "yes", "name": "yes", "capabilities": {"home_assistant": True}},
                {"id": "no", "name": "no", "capabilities": {"home_assistant": False}},
                {"id": "odd", "name": "odd", "capabilities": {"home_assistant": "1"}},
                {"id": "flat", "name": "flat", "capabilities": ["home_assistant"]},
            ],
            "meta": {},
        }
    )
    plane.list_public_hubs = AsyncMock(
        return_value={
            "data": [
                {
                    "id": "desk",
                    "title": "Daily Desk",
                    "capabilities": {"home_assistant": True},
                }
            ],
            "meta": {},
        }
    )

    hubs = await ThalovantApi(MagicMock(), _tokens()).list_hubs()
    assert {hub.id: hub.can_link for hub in hubs} == {
        "yes": True,
        "no": False,
        "odd": None,
        "flat": None,
        "desk": True,
    }


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
        # A 429 is still a connection error (try later), now a kind of its own.
        (
            SdkAPIError("busy", status_code=429),
            ThalovantRateLimitedError,
            {"status": 429},
        ),
        (
            SdkAPIError("down", status_code=503),
            ThalovantConnectionError,
            {"status": 503},
        ),
        (SdkHubRefusedError("refused"), ThalovantAuthError, {"status": None}),
        # The hub refusing this connection's own key: a refusal that says why.
        (
            SdkClientKeyRejectedError("key rejected", key_folder="/x"),
            ThalovantClientKeyRejectedError,
            {"status": None},
        ),
        # A changed hub key is not a refusal and not a blip.
        (SdkHubKeyChangedError("key changed"), ThalovantHubKeyChangedError, {}),
        (SdkAdmissionTimeoutError("slow"), ThalovantAdmissionTimeoutError, {}),
        (
            SdkAdmissionFailedError("failed", error_code="op_failed"),
            ThalovantAdmissionFailedError,
            {"code": "op_failed", "status": None},
        ),
        (
            SdkAdmissionFailedError(
                "refused", status_code=400, code="bad_operation", detail="No."
            ),
            ThalovantAdmissionFailedError,
            {"status": 400, "code": "bad_operation", "detail": "No."},
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
    link.run = AsyncMock(side_effect=SdkClientKeyRejectedError("key rejected"))
    with pytest.raises(ThalovantClientKeyRejectedError):
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


# --- Intercom ----------------------------------------------------------------


def _sdk_announcement(status: str = "completed", **fields: Any) -> SimpleNamespace:
    """What the SDK's Announcement looks like to the adapter."""
    return SimpleNamespace(
        id="ann-1",
        status=status,
        priority="normal",
        deliveries=[
            SimpleNamespace(status="delivered"),
            SimpleNamespace(status="offline"),
            SimpleNamespace(status="delivered"),
        ],
        acked_by=fields.get("acked_by"),
        hub_confirmed=fields.get("hub_confirmed"),
        replayed=fields.get("replayed", False),
    )


async def test_intercom_reads(sdk: SimpleNamespace) -> None:
    """Settings and speakers become the integration's own types."""
    plane = sdk.AsyncThalovantControlPlane.return_value
    plane.get_intercom_settings = AsyncMock(
        return_value=SimpleNamespace(
            enabled=True, plan_allowed=True, unavailable_reason=" platform "
        )
    )
    plane.list_intercom_speakers = AsyncMock(
        return_value=SimpleNamespace(
            items=[
                SimpleNamespace(
                    client_id="c1",
                    slug="kitchen",
                    name="Kitchen",
                    online=True,
                    kind="voice_satellite",
                    can_play=True,
                    intercom=SimpleNamespace(
                        receive=True, room="kitchen", groups=("down",)
                    ),
                ),
                SimpleNamespace(
                    client_id="c2",
                    slug=None,
                    name=None,
                    online=False,
                    kind="home_assistant",
                    can_play=False,
                    intercom=SimpleNamespace(receive=False, room=None, groups=()),
                ),
                # An answer with neither: the platform's own default is "can play".
                SimpleNamespace(
                    client_id="c3",
                    slug=None,
                    name=None,
                    online=False,
                    kind="  ",
                    intercom=SimpleNamespace(receive=False, room=None, groups=()),
                ),
            ],
            policy_synced=False,
            unavailable_reason="platform",
        )
    )
    api_ = ThalovantApi(MagicMock(), _tokens())

    settings = await api_.get_intercom_settings(HUB_ID)
    assert (settings.enabled, settings.plan_allowed, settings.unavailable_reason) == (
        True,
        True,
        "platform",
    )
    plane.get_intercom_settings.assert_awaited_once_with(HUB_ID)

    speakers = await api_.list_intercom_speakers(HUB_ID)
    assert [
        (s.client_id, s.online, s.receive, s.room, s.groups, s.kind, s.can_play)
        for s in speakers.items
    ] == [
        ("c1", True, True, "kitchen", ("down",), "voice_satellite", True),
        ("c2", False, False, None, (), "home_assistant", False),
        ("c3", False, False, None, (), "voice_satellite", True),
    ]
    assert (speakers.policy_synced, speakers.unavailable_reason) == (False, "platform")

    # A listing that says neither says so.
    plane.list_intercom_speakers = AsyncMock(return_value=SimpleNamespace(items=[]))
    empty = await api_.list_intercom_speakers(HUB_ID)
    assert (empty.items, empty.policy_synced, empty.unavailable_reason) == (
        (),
        None,
        None,
    )


async def test_announce_passes_everything_and_keeps_no_text(
    sdk: SimpleNamespace,
) -> None:
    """One call to the SDK, with the text, the key and the repeat; an answer with no text."""
    plane = sdk.AsyncThalovantControlPlane.return_value
    plane.announce = AsyncMock(
        return_value=_sdk_announcement("sending", hub_confirmed=None)
    )
    api_ = ThalovantApi(MagicMock(), _tokens())

    result = await api_.announce(
        HUB_ID,
        "Secret words",
        targets={"rooms": ["kitchen"]},
        priority="urgent",
        repeat=(3, 30),
        lang="fr",
        idempotency_key="k-1",
    )

    plane.announce.assert_awaited_once_with(
        HUB_ID,
        "Secret words",
        {"rooms": ["kitchen"]},
        priority="urgent",
        repeat={"times": 3, "interval_seconds": 30},
        lang="fr",
        idempotency_key="k-1",
    )
    assert result.id == "ann-1"
    assert result.status == "sending"
    assert result.delivery_counts == {"delivered": 2, "offline": 1}
    assert result.hub_confirmed is None
    assert result.replayed is False
    assert "Secret words" not in repr(result)

    plane.announce.reset_mock()
    await api_.announce(
        HUB_ID,
        "x",
        targets={"all": True},
        priority="normal",
        repeat=None,
        lang=None,
        idempotency_key="k-2",
    )
    assert plane.announce.await_args.kwargs["repeat"] is None


async def test_announcement_reads_and_cancel(sdk: SimpleNamespace) -> None:
    """Reading and cancelling map the same way; a cancel says whether the hub confirmed."""
    plane = sdk.AsyncThalovantControlPlane.return_value
    plane.get_announcement = AsyncMock(return_value=_sdk_announcement())
    plane.cancel_announcement = AsyncMock(
        return_value=_sdk_announcement(
            "cancelled", hub_confirmed=False, acked_by=" Kitchen "
        )
    )
    api_ = ThalovantApi(MagicMock(), _tokens())
    assert (await api_.get_announcement(HUB_ID, "ann-1")).status == "completed"
    plane.announce = AsyncMock(return_value=_sdk_announcement("failed", replayed=True))
    replayed = await api_.announce(
        HUB_ID,
        "x",
        targets={"all": True},
        priority="normal",
        repeat=None,
        lang=None,
        idempotency_key="k",
    )
    # An announcement the platform already had: nothing new was sent.
    assert (replayed.status, replayed.replayed) == ("failed", True)
    cancelled = await api_.cancel_announcement(HUB_ID, "ann-1")
    assert (cancelled.status, cancelled.hub_confirmed, cancelled.acked_by) == (
        "cancelled",
        False,
        "Kitchen",
    )
    plane.cancel_announcement.assert_awaited_once_with(HUB_ID, "ann-1")


@pytest.mark.parametrize(
    ("raised", "expected", "attrs"),
    [
        (
            SdkRateLimitedError("slow down", status_code=429, retry_after_seconds=7),
            api.ThalovantRateLimitedError,
            {"retry_after": 7.0, "status": 429},
        ),
        (
            SdkAPIError("slow down", status_code=429),
            api.ThalovantRateLimitedError,
            {"retry_after": None},
        ),
        (
            SdkHubUnreachableError("gone", status_code=502, announcement_id="a-9"),
            api.ThalovantHubUnreachableError,
            {"announcement_id": "a-9", "status": 502},
        ),
        (
            SdkAPIError("gone", status_code=502, code="hub_unreachable"),
            api.ThalovantHubUnreachableError,
            {"announcement_id": None},
        ),
        (
            SdkNotCancellableError(
                "done", status_code=409, problem={"announcement_status": "completed"}
            ),
            api.ThalovantNotCancellableError,
            {"announcement_status": "completed"},
        ),
        (
            SdkAPIError("done", status_code=409, code="not_cancellable"),
            api.ThalovantNotCancellableError,
            {"announcement_status": None},
        ),
        (
            SdkIntercomDisabledError("off", status_code=403, code="intercom_disabled"),
            api.ThalovantIntercomUnavailableError,
            {"reason": "hub_off"},
        ),
        (
            SdkIntercomDisabledError("off", status_code=403),
            api.ThalovantIntercomUnavailableError,
            {"reason": "hub_off"},
        ),
        (
            SdkAPIError("dark", status_code=503, code="intercom_disabled_platform"),
            api.ThalovantIntercomUnavailableError,
            {"reason": "platform", "status": 503},
        ),
        (
            SdkAPIError("no key", status_code=503, code="intercom_not_configured"),
            api.ThalovantIntercomUnavailableError,
            {"reason": "not_configured"},
        ),
        (
            SdkHubUnreachableError("gone", status_code=502),
            api.ThalovantHubUnreachableError,
            {"announcement_id": None},
        ),
        (
            SdkAPIError(
                "gone",
                status_code=502,
                code="hub_unreachable",
                problem={"announcement_id": " a-1 "},
            ),
            api.ThalovantHubUnreachableError,
            {"announcement_id": "a-1"},
        ),
        (
            SdkAPIError(
                "done",
                status_code=409,
                code="not_cancellable",
                problem={"detail": {"announcement_status": "failed"}},
            ),
            api.ThalovantNotCancellableError,
            {"announcement_status": "failed"},
        ),
        (
            SdkIntercomPlatformDisabledError(
                "dark", status_code=503, code="intercom_disabled_platform"
            ),
            api.ThalovantIntercomUnavailableError,
            {"reason": "platform"},
        ),
        (
            SdkIntercomNotConfiguredError("no key", status_code=503),
            api.ThalovantIntercomUnavailableError,
            {"reason": "not_configured"},
        ),
        (
            SdkIntercomUnavailableError(
                "never", status_code=422, code="intercom_unavailable", reason="kid_hub"
            ),
            api.ThalovantIntercomUnavailableError,
            {"reason": "kid_hub", "status": 422},
        ),
        (
            SdkAPIError(
                "never",
                status_code=422,
                code="intercom_unavailable",
                problem={"reason": "public_hub"},
            ),
            api.ThalovantIntercomUnavailableError,
            {"reason": "public_hub"},
        ),
        (
            SdkAPIError(
                "never",
                status_code=422,
                code="intercom_unavailable",
                problem={"detail": {"reason": "kid_hub"}},
            ),
            api.ThalovantIntercomUnavailableError,
            {"reason": "kid_hub"},
        ),
        # A reason nobody knows, or none, is still "Intercom is unavailable".
        (
            SdkAPIError(
                "never",
                status_code=422,
                code="intercom_unavailable",
                problem={"reason": "moon"},
            ),
            api.ThalovantIntercomUnavailableError,
            {"reason": "unknown"},
        ),
        (
            SdkIntercomUnavailableError("never", status_code=422),
            api.ThalovantIntercomUnavailableError,
            {"reason": "unknown"},
        ),
        # An urgent announcement without intercom:urgent is a missing scope, not
        # a rejected sign-in, although the SDK's class is a kind of auth error.
        (
            SdkUrgentScopeRequiredError(
                "scope", status_code=403, code="urgent_scope_required"
            ),
            api.ThalovantUrgentScopeRequiredError,
            {"status": 403, "code": "urgent_scope_required"},
        ),
        (
            SdkAuthError("scope", status_code=403, code="urgent_scope_required"),
            api.ThalovantUrgentScopeRequiredError,
            {},
        ),
        (
            SdkUrgentBusyError(
                "busy",
                status_code=429,
                code="intercom_urgent_busy",
                retry_after_seconds=30,
            ),
            api.ThalovantUrgentBusyError,
            {"retry_after": 30.0, "status": 429},
        ),
        (
            SdkAPIError("busy", status_code=429, code="intercom_urgent_busy"),
            api.ThalovantUrgentBusyError,
            {"retry_after": None},
        ),
        (
            SdkSkillNotInstalledError("no skill", status_code=409),
            api.ThalovantSkillNotInstalledError,
            {"status": 409},
        ),
        (
            SdkAPIError("no skill", status_code=409, code="skill_not_installed"),
            api.ThalovantSkillNotInstalledError,
            {},
        ),
        (
            SdkNotASpeakerError("no", status_code=422, code="not_a_speaker"),
            api.ThalovantNotASpeakerError,
            {"status": 422},
        ),
        (
            SdkAPIError("no", status_code=422, code="not_a_speaker"),
            api.ThalovantNotASpeakerError,
            {},
        ),
        (
            SdkTooManyTargetsError("many", status_code=422, code="too_many_targets"),
            api.ThalovantTooManyTargetsError,
            {},
        ),
        (
            SdkAPIError("many", status_code=422, code="too_many_targets"),
            api.ThalovantTooManyTargetsError,
            {},
        ),
        (
            SdkHubLockedError("locked", status_code=403, code="hub_locked"),
            api.ThalovantHubLockedError,
            {"status": 403},
        ),
        (
            SdkAPIError("locked", status_code=403, code="hub_locked"),
            api.ThalovantHubLockedError,
            {},
        ),
        # Another 503 is still a service that is down, not Intercom's answer.
        (
            SdkAPIError("down", status_code=503, code="overloaded"),
            ThalovantConnectionError,
            {"status": 503},
        ),
        # And another 502 is the platform's own, not a hub that was not reached.
        (
            SdkAPIError("bad gateway", status_code=502, code="upstream"),
            ThalovantConnectionError,
            {"status": 502},
        ),
    ],
)
async def test_intercom_errors(
    sdk: SimpleNamespace,
    raised: Exception,
    expected: type[ThalovantError],
    attrs: dict[str, Any],
) -> None:
    """Each Intercom answer is its own error, by SDK class or by status and code."""
    plane = sdk.AsyncThalovantControlPlane.return_value
    plane.announce = AsyncMock(side_effect=raised)
    with pytest.raises(ThalovantError) as caught:
        await ThalovantApi(MagicMock(), _tokens()).announce(
            HUB_ID,
            "x",
            targets={"all": True},
            priority="normal",
            repeat=None,
            lang=None,
            idempotency_key="k",
        )
    assert type(caught.value) is expected
    for name, value in attrs.items():
        assert getattr(caught.value, name) == value
    assert plane.announce.await_count == 1


def _connection_plane(
    sdk: SimpleNamespace, client: Any, request: Any | None
) -> SimpleNamespace:
    plane = SimpleNamespace(get_client=AsyncMock(side_effect=client))
    if request is not None:
        plane._request = request
    sdk.AsyncThalovantControlPlane.return_value = plane
    return plane


async def test_can_play_writes_the_whole_spec_with_the_etag(
    sdk: SimpleNamespace,
) -> None:
    """The spec is read and written back under its etag with can_play as the only intercom key."""
    spec = {
        "connection_type": "home_assistant",
        "allowedTypes": ["a"],
        "intercom": {"receive": True, "room": "kitchen"},
    }
    request = AsyncMock()
    plane = _connection_plane(sdk, [{"spec": spec, "etag": "e-1"}], request)
    await ThalovantApi(MagicMock(), _tokens()).set_connection_can_play("c/1", True)
    plane.get_client.assert_awaited_once_with("c/1")
    request.assert_awaited_once_with(
        "PATCH",
        "/v1/clients/c%2F1",
        json={
            "spec": {
                "connection_type": "home_assistant",
                "allowedTypes": ["a"],
                # The platform owns the rest of spec.intercom: a caller may say
                # only can_play, so nothing else of it is sent back.
                "intercom": {"can_play": True},
            }
        },
        headers={"If-Match": "e-1"},
    )
    # What was read is not changed in place.
    assert spec["intercom"] == {"receive": True, "room": "kitchen"}


async def test_can_play_already_set_writes_nothing(sdk: SimpleNamespace) -> None:
    """A connection that already says so is left alone."""
    request = AsyncMock()
    _connection_plane(
        sdk, [{"spec": {"intercom": {"can_play": False}}, "etag": "e"}], request
    )
    await ThalovantApi(MagicMock(), _tokens()).set_connection_can_play("c", False)
    request.assert_not_awaited()


async def test_can_play_without_an_intercom_key(sdk: SimpleNamespace) -> None:
    """A connection with no intercom settings gets them."""
    request = AsyncMock()
    _connection_plane(sdk, [{"spec": {"intercom": "odd"}, "etag": "e"}], request)
    await ThalovantApi(MagicMock(), _tokens()).set_connection_can_play("c", True)
    assert request.await_args.kwargs["json"] == {
        "spec": {"intercom": {"can_play": True}}
    }


async def test_can_play_retries_a_changed_connection_once(
    sdk: SimpleNamespace,
) -> None:
    """A 412 means somebody else wrote first: read it again, then write."""
    request = AsyncMock(side_effect=[SdkAPIError("stale", status_code=412), None])
    plane = _connection_plane(
        sdk,
        [{"spec": {}, "etag": "e-1"}, {"spec": {}, "etag": "e-2"}],
        request,
    )
    await ThalovantApi(MagicMock(), _tokens()).set_connection_can_play("c", True)
    assert plane.get_client.await_count == 2
    assert [call.kwargs["headers"] for call in request.await_args_list] == [
        {"If-Match": "e-1"},
        {"If-Match": "e-2"},
    ]


async def test_can_play_gives_up_after_one_retry(sdk: SimpleNamespace) -> None:
    """A second 412 is the error; any other error is too, at once."""
    request = AsyncMock(side_effect=SdkAPIError("stale", status_code=412))
    _connection_plane(
        sdk, [{"spec": {}, "etag": "e-1"}, {"spec": {}, "etag": "e-2"}], request
    )
    with pytest.raises(ThalovantApiError) as caught:
        await ThalovantApi(MagicMock(), _tokens()).set_connection_can_play("c", True)
    assert caught.value.status == 412
    assert request.await_count == 2

    request = AsyncMock(side_effect=SdkAPIError("no", status_code=403))
    _connection_plane(sdk, [{"spec": {}, "etag": "e-1"}], request)
    with pytest.raises(ThalovantApiError) as caught:
        await ThalovantApi(MagicMock(), _tokens()).set_connection_can_play("c", True)
    assert caught.value.status == 403
    assert request.await_count == 1


@pytest.mark.parametrize(
    "client",
    [
        {"etag": "e"},
        {"spec": {}, "etag": ""},
        {"spec": [], "etag": "e"},
        {"spec": {}},
        "odd",
    ],
)
async def test_can_play_needs_a_spec_and_an_etag(
    sdk: SimpleNamespace, client: Any
) -> None:
    """A connection read without them cannot be written back safely."""
    request = AsyncMock()
    _connection_plane(sdk, [client], request)
    with pytest.raises(ThalovantApiError, match="spec or an etag"):
        await ThalovantApi(MagicMock(), _tokens()).set_connection_can_play("c", True)
    request.assert_not_awaited()


async def test_can_play_needs_an_sdk_that_can_write(sdk: SimpleNamespace) -> None:
    """An SDK without the private call that writes is a clear error, not an AttributeError."""
    _connection_plane(sdk, [], None)
    with pytest.raises(ThalovantError, match="cannot update a connection"):
        await ThalovantApi(MagicMock(), _tokens()).set_connection_can_play("c", True)
