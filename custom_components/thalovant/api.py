"""The integration's only door to the Thalovant SDK.

Nothing else in the integration imports the SDK. Everything here has the shape
the shared contract (CONTRACT.md, v1) gives the library interface, and it
belongs to the integration: config entries store the to_dict() forms of Tokens
and ConnectionCredentials, and tests patch ThalovantAuth, ThalovantApi and
HubConnection.

Underneath, each call goes to the async API of the ``thalovant`` SDK under the
contract's names (see SDK_NAMES). SDK objects are turned into the types below
on the way out, and SDK errors into the errors below. When the SDK's async
names settle, this file is the only one that changes.
"""

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
import importlib
from types import MappingProxyType
from typing import Any, Final, Self, cast

import aiohttp

SDK_MODULE: Final = "thalovant"


def _load_sdk() -> Any:
    """Import the SDK once, when Home Assistant imports this integration.

    Home Assistant installs it from the manifest's requirements first; the
    tests run without it and patch the classes below.
    """
    try:
        return importlib.import_module(SDK_MODULE)
    except ImportError:
        return None


_sdk_module: Any = _load_sdk()

# Everything this file takes from the SDK, by name.
SDK_NAMES: Final = (
    "ThalovantAuth",
    "ThalovantApi",
    "HubConnection",
    "DeviceLogin",
    "Tokens",
    "ConnectionCredentials",
    "ThalovantError",
    "ThalovantAuthError",
    "ThalovantConnectionError",
    "ThalovantApiError",
    "ThalovantPlanError",
    "ThalovantAlreadyLinkedError",
    "ThalovantUnsupportedError",
    "DeviceLoginPending",
    "DeviceLoginExpired",
    "DeviceLoginDenied",
)


class ThalovantError(Exception):
    """Any failure talking to Thalovant.

    An error built from an API answer carries its HTTP status, the problem's
    code and its sentence.
    """

    def __init__(
        self,
        message: str = "",
        *,
        status: int | None = None,
        code: str | None = None,
        detail: str | None = None,
    ) -> None:
        """Keep what the API said."""
        super().__init__(message)
        self.status = status
        self.code = code
        self.detail = detail


class ThalovantAuthError(ThalovantError):
    """The API token or the connection's credentials were rejected."""


class ThalovantConnectionError(ThalovantError):
    """Network, DNS, TLS, a 5xx or 429 answer, or a hub out of reach."""


class ThalovantApiError(ThalovantError):
    """The API refused for a reason signing in again will not fix."""


class ThalovantPlanError(ThalovantApiError):
    """The plan does not allow it: 402, or 403 with code plan_limit."""


class ThalovantAlreadyLinkedError(ThalovantApiError):
    """Another connection already links Home Assistant to this hub (409)."""

    def __init__(
        self,
        message: str = "",
        *,
        connection_id: str | None = None,
        status: int | None = None,
        code: str | None = None,
        detail: str | None = None,
    ) -> None:
        """Keep the id of the connection that holds the link, when named."""
        super().__init__(message, status=status, code=code, detail=detail)
        self.connection_id = connection_id


class ThalovantUnsupportedError(ThalovantApiError):
    """The API or the hub cannot make a Home Assistant connection yet."""


class DeviceLoginPending(ThalovantError):
    """Not approved yet; poll again after interval seconds."""

    def __init__(self, message: str = "", *, interval: int) -> None:
        """Keep the interval, already longer after a slow_down."""
        super().__init__(message)
        self.interval = interval


class DeviceLoginExpired(ThalovantError):
    """The code expired before it was approved."""


class DeviceLoginDenied(ThalovantError):
    """The person declined the sign-in."""


@dataclass(frozen=True, slots=True)
class DeviceLogin:
    """A started device login."""

    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str | None
    interval: int
    expires_in: int
    sdk: Any = field(default=None, repr=False, compare=False)


def _text(data: Mapping[str, Any], key: str, *, optional: bool = False) -> Any:
    """Read a string field for from_dict, which raises ValueError on bad data."""
    value = data.get(key)
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} is missing or not a string")
    return value


@dataclass(frozen=True, slots=True)
class Tokens:
    """The API token from a device login. The form stored in the entry."""

    access_token: str = field(repr=False)
    refresh_token: str | None = field(repr=False)
    expires_at: datetime | None
    scopes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe form."""
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "scopes": list(self.scopes),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        """Read what to_dict() wrote. Raises ValueError on bad data."""
        if not isinstance(data, Mapping):
            raise ValueError("tokens are not a mapping")  # noqa: TRY004 - one error type for bad data
        expires_at = _text(data, "expires_at", optional=True)
        scopes = data.get("scopes", ())
        if not isinstance(scopes, (list, tuple)) or not all(
            isinstance(scope, str) for scope in scopes
        ):
            raise ValueError("scopes is not a list of strings")
        return cls(
            access_token=_text(data, "access_token"),
            refresh_token=_text(data, "refresh_token", optional=True),
            expires_at=datetime.fromisoformat(expires_at) if expires_at else None,
            scopes=tuple(scopes),
        )


@dataclass(frozen=True, slots=True)
class Account:
    """The signed-in Thalovant account."""

    id: str
    display_name: str | None
    email: str | None


@dataclass(frozen=True, slots=True)
class Hub:
    """A hub the account may link."""

    id: str
    name: str
    public: bool
    languages: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ConnectionCredentials:
    """What reaches a hub. The form stored in the entry; secret is opaque."""

    hub_id: str
    connection_id: str
    name: str
    endpoint: str
    secret: Mapping[str, str] = field(repr=False, hash=False)
    operation_url: str | None = None

    def __post_init__(self) -> None:
        """Freeze the secret."""
        object.__setattr__(self, "secret", MappingProxyType(dict(self.secret)))

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe form. It contains the connection's secrets."""
        return {
            "hub_id": self.hub_id,
            "connection_id": self.connection_id,
            "name": self.name,
            "endpoint": self.endpoint,
            "secret": dict(self.secret),
            "operation_url": self.operation_url,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        """Read what to_dict() wrote. Raises ValueError on bad data."""
        if not isinstance(data, Mapping):
            raise ValueError("credentials are not a mapping")  # noqa: TRY004 - one error type for bad data
        secret = data.get("secret")
        if not isinstance(secret, Mapping) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in secret.items()
        ):
            raise ValueError("secret is missing or not a mapping of strings")
        return cls(
            hub_id=_text(data, "hub_id"),
            connection_id=_text(data, "connection_id"),
            name=_text(data, "name"),
            endpoint=_text(data, "endpoint"),
            secret=secret,
            operation_url=_text(data, "operation_url", optional=True),
        )


@dataclass(frozen=True, slots=True)
class HubMessage:
    """A message from the hub. Reply to it with HubConnection.reply()."""

    type: str
    data: Mapping[str, Any]
    context: Mapping[str, Any]
    sdk: Any = field(default=None, repr=False, compare=False)


def _sdk(name: str) -> Any:
    """Return one of SDK_NAMES from the installed SDK."""
    if _sdk_module is None:
        raise ThalovantError("The thalovant SDK is not installed")
    try:
        return getattr(_sdk_module, name)
    except AttributeError as err:
        raise ThalovantError(f"The installed thalovant SDK has no {name}") from err


# Most specific first: the first SDK class the error is an instance of wins.
_ERRORS: Final[tuple[tuple[str, type[ThalovantError]], ...]] = (
    ("DeviceLoginPending", DeviceLoginPending),
    ("DeviceLoginExpired", DeviceLoginExpired),
    ("DeviceLoginDenied", DeviceLoginDenied),
    ("ThalovantAuthError", ThalovantAuthError),
    ("ThalovantConnectionError", ThalovantConnectionError),
    ("ThalovantPlanError", ThalovantPlanError),
    ("ThalovantAlreadyLinkedError", ThalovantAlreadyLinkedError),
    ("ThalovantUnsupportedError", ThalovantUnsupportedError),
    ("ThalovantApiError", ThalovantApiError),
    ("ThalovantError", ThalovantError),
)


def _translate(err: Exception) -> ThalovantError | None:
    """Turn an SDK error into ours; None for anything that is not one."""
    for name, ours in _ERRORS:
        theirs = getattr(_sdk_module, name, None)
        if not isinstance(theirs, type) or not isinstance(err, theirs):
            continue
        if ours is DeviceLoginPending:
            return DeviceLoginPending(
                str(err), interval=int(getattr(err, "interval", 0) or 0)
            )
        facts: dict[str, Any] = {
            "status": getattr(err, "status", None),
            "code": getattr(err, "code", None),
            "detail": getattr(err, "detail", None),
        }
        if ours is ThalovantAlreadyLinkedError:
            facts["connection_id"] = getattr(err, "connection_id", None)
        return ours(str(err), **facts)
    return None


@asynccontextmanager
async def _translated() -> AsyncIterator[None]:
    """Raise the SDK's errors as this module's."""
    try:
        yield
    except ThalovantError:
        raise
    except Exception as err:
        if (ours := _translate(err)) is None:
            raise
        raise ours from err


class ThalovantAuth:
    """Device login against the control plane."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        """Use Home Assistant's shared session."""
        self._session = session
        self._client: Any = None

    def _auth(self) -> Any:
        if self._client is None:
            self._client = _sdk("ThalovantAuth")(self._session)
        return self._client

    async def start_device_login(
        self, *, client_name: str, scopes: Sequence[str]
    ) -> DeviceLogin:
        """Ask for a device code."""
        async with _translated():
            login = await self._auth().start_device_login(
                client_name=client_name, scopes=list(scopes)
            )
        return DeviceLogin(
            device_code=login.device_code,
            user_code=login.user_code,
            verification_uri=login.verification_uri,
            verification_uri_complete=login.verification_uri_complete,
            interval=int(login.interval),
            expires_in=int(login.expires_in),
            sdk=login,
        )

    async def poll_device_login(self, login: DeviceLogin) -> Tokens:
        """Poll once: the tokens, or DeviceLoginPending, Expired or Denied."""
        async with _translated():
            sdk_login = login.sdk
            if sdk_login is None:
                sdk_login = _sdk("DeviceLogin")(
                    device_code=login.device_code,
                    user_code=login.user_code,
                    verification_uri=login.verification_uri,
                    verification_uri_complete=login.verification_uri_complete,
                    interval=login.interval,
                    expires_in=login.expires_in,
                )
            tokens = await self._auth().poll_device_login(sdk_login)
        return Tokens.from_dict(tokens.to_dict())


class ThalovantApi:
    """The control plane, as the signed-in account."""

    def __init__(self, session: aiohttp.ClientSession, tokens: Tokens) -> None:
        """Use Home Assistant's shared session and the account's token."""
        self._session = session
        self._tokens = tokens
        self._client: Any = None

    def _api(self) -> Any:
        if self._client is None:
            sdk_tokens = _sdk("Tokens").from_dict(self._tokens.to_dict())
            self._client = _sdk("ThalovantApi")(self._session, sdk_tokens)
        return self._client

    async def get_account(self) -> Account:
        """Return the signed-in account."""
        async with _translated():
            account = await self._api().get_account()
        return Account(
            id=account.id, display_name=account.display_name, email=account.email
        )

    async def list_hubs(self) -> list[Hub]:
        """Return the hubs this account may link."""
        async with _translated():
            hubs = await self._api().list_hubs()
        return [
            Hub(
                id=hub.id,
                name=hub.name,
                public=bool(hub.public),
                languages=tuple(hub.languages),
            )
            for hub in hubs
        ]

    async def create_connection(
        self, hub_id: str, *, name: str, kind: str
    ) -> ConnectionCredentials:
        """Create this installation's connection on a hub."""
        async with _translated():
            credentials = await self._api().create_connection(
                hub_id, name=name, kind=kind
            )
        return ConnectionCredentials.from_dict(credentials.to_dict())

    async def wait_for_admission(
        self, credentials: ConnectionCredentials, *, timeout: float
    ) -> None:
        """Return once the hub has admitted the connection."""
        async with _translated():
            sdk_credentials = _sdk("ConnectionCredentials").from_dict(
                credentials.to_dict()
            )
            await self._api().wait_for_admission(sdk_credentials, timeout=timeout)

    async def delete_connection(self, connection_id: str) -> None:
        """Delete a connection; one already gone counts as deleted."""
        async with _translated():
            await self._api().delete_connection(connection_id)


class HubConnection:
    """The outbound link to one hub."""

    def __init__(
        self, session: aiohttp.ClientSession, credentials: ConnectionCredentials
    ) -> None:
        """Prepare the link. Raises ValueError if the credentials are unusable."""
        sdk_credentials = _sdk("ConnectionCredentials").from_dict(credentials.to_dict())
        self._connection = _sdk("HubConnection")(session, sdk_credentials)

    @property
    def connected(self) -> bool:
        """Whether the link is up."""
        return bool(self._connection.connected)

    async def connect(self) -> None:
        """Make one attempt; raises ThalovantAuthError or ThalovantConnectionError."""
        async with _translated():
            await self._connection.connect()

    async def run(self) -> None:
        """Stay connected until close(); raises ThalovantAuthError if refused."""
        async with _translated():
            await self._connection.run()

    async def close(self) -> None:
        """Close the link."""
        async with _translated():
            await self._connection.close()

    def on_state_change(self, callback: Callable[[bool], None]) -> Callable[[], None]:
        """Call back with the new state on every change; returns the unsubscribe."""
        return cast(Callable[[], None], self._connection.on_state_change(callback))

    def on_message(
        self,
        msg_type: str,
        callback: Callable[[HubMessage], Awaitable[None] | None],
    ) -> Callable[[], None]:
        """Call back for every message of one type; returns the unsubscribe."""

        def relay(message: Any) -> Awaitable[None] | None:
            return callback(
                HubMessage(
                    type=message.type,
                    data=message.data,
                    context=message.context,
                    sdk=message,
                )
            )

        return cast(Callable[[], None], self._connection.on_message(msg_type, relay))

    async def reply(
        self, request: HubMessage, msg_type: str, data: Mapping[str, Any]
    ) -> None:
        """Answer a message, keeping its context, session and routing."""
        async with _translated():
            await self._connection.reply(request.sdk, msg_type, data)
