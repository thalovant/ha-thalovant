"""A stand-in for aiothalovant, built from the shared contract.

The integration is developed alongside the library, so the test suite runs
against this module (contract v1) instead of whatever state the library is in. It mirrors the
public names and signatures in CONTRACT.md; the classes do nothing on their
own and every test replaces them with mocks. Set AIOTHALOVANT=real to run the
suite against an installed library instead.
"""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Self

import aiohttp

DEFAULT_API_URL = "https://api.thalovant.com"
DEFAULT_SCOPES = ("hubs:read", "clients:read", "clients:write")
KIND_HOME_ASSISTANT = "home_assistant"
HOME_REQUEST = "thalovant.home.request"
HOME_RESPONSE = "thalovant.home.response"


class ThalovantError(Exception):
    """Base error. API errors carry what the control plane said."""

    def __init__(
        self,
        message: str = "",
        *,
        status: int | None = None,
        code: str | None = None,
        detail: str | None = None,
        problem: Mapping[str, Any] | None = None,
    ) -> None:
        """Keep the response's status, problem code and sentence."""
        super().__init__(message)
        self.status = status
        self.code = code
        self.detail = detail
        self.problem = dict(problem) if problem is not None else None


class ThalovantAuthError(ThalovantError):
    """Token or connection credentials rejected."""


class ThalovantConnectionError(ThalovantError):
    """Network, DNS, TLS, 5xx, or hub unreachable."""


class ThalovantApiError(ThalovantError):
    """Any other API refusal; status, code and detail say which."""


class ThalovantPlanError(ThalovantApiError):
    """402, or 403 with code plan_limit."""


class ThalovantAlreadyLinkedError(ThalovantApiError):
    """409 home_assistant_already_linked."""

    def __init__(
        self, message: str = "", *, connection_id: str | None = None, **kwargs: Any
    ) -> None:
        """Keep the id of the connection that already holds the link."""
        super().__init__(message, **kwargs)
        self.connection_id = connection_id


class ThalovantUnsupportedError(ThalovantApiError):
    """The API or the hub cannot make this kind of connection yet."""


class DeviceLoginPending(ThalovantError):
    """The user has not approved the login yet; keep polling."""

    def __init__(self, message: str = "", *, interval: int) -> None:
        """Carry the interval to wait, already longer after slow_down."""
        super().__init__(message)
        self.interval = interval


class DeviceLoginExpired(ThalovantError):
    """The device code expired."""


class DeviceLoginDenied(ThalovantError):
    """The user declined the login."""


@dataclass(frozen=True, slots=True)
class DeviceLogin:
    """A started device login."""

    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str | None
    interval: int
    expires_in: int


@dataclass(frozen=True, slots=True)
class Tokens:
    """API tokens from a device login."""

    access_token: str
    refresh_token: str | None
    expires_at: datetime | None
    scopes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-safe primitives."""
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "scopes": list(self.scopes),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        """Deserialize."""
        expires_at = data.get("expires_at")
        return cls(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_at=datetime.fromisoformat(expires_at) if expires_at else None,
            scopes=tuple(data.get("scopes", ())),
        )


@dataclass(frozen=True, slots=True)
class Account:
    """A Thalovant account."""

    id: str
    display_name: str | None
    email: str | None


@dataclass(frozen=True, slots=True)
class Hub:
    """A hub the account may attach a connection to."""

    id: str
    name: str
    public: bool
    languages: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ConnectionCredentials:
    """What a HubConnection needs to reach its hub."""

    hub_id: str
    connection_id: str
    name: str
    endpoint: str
    secret: Mapping[str, str]
    operation_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-safe primitives."""
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
        """Deserialize."""
        return cls(
            hub_id=data["hub_id"],
            connection_id=data["connection_id"],
            name=data["name"],
            endpoint=data["endpoint"],
            secret=dict(data["secret"]),
            operation_url=data.get("operation_url"),
        )


@dataclass(frozen=True, slots=True)
class HubMessage:
    """A message received from the hub."""

    type: str
    data: Mapping[str, Any]
    context: Mapping[str, Any]


class ThalovantAuth:
    """Device login against the control plane."""

    def __init__(
        self, session: aiohttp.ClientSession, *, api_url: str = DEFAULT_API_URL
    ) -> None:
        """Initialize."""

    async def start_device_login(
        self, *, client_name: str, scopes: Sequence[str]
    ) -> DeviceLogin:
        """Start a device login."""
        raise NotImplementedError

    async def poll_device_login(self, login: DeviceLogin) -> Tokens:
        """Poll once."""
        raise NotImplementedError


class ThalovantApi:
    """The control plane API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        tokens: Tokens,
        *,
        api_url: str = DEFAULT_API_URL,
    ) -> None:
        """Initialize."""

    async def get_account(self) -> Account:
        """Return the signed-in account."""
        raise NotImplementedError

    async def list_hubs(self) -> list[Hub]:
        """Return the hubs this account may attach a connection to."""
        raise NotImplementedError

    async def create_connection(
        self, hub_id: str, *, name: str, kind: str = "home_assistant"
    ) -> ConnectionCredentials:
        """Create a connection on a hub."""
        raise NotImplementedError

    async def wait_for_admission(
        self, credentials: ConnectionCredentials, *, timeout: float = 180
    ) -> None:
        """Wait until the hub has admitted the connection."""
        raise NotImplementedError

    async def delete_connection(self, connection_id: str) -> None:
        """Delete a connection."""
        raise NotImplementedError


class HubConnection:
    """The outbound link to a hub."""

    def __init__(
        self, session: aiohttp.ClientSession, credentials: ConnectionCredentials
    ) -> None:
        """Initialize."""

    async def connect(self) -> None:
        """Connect once."""
        raise NotImplementedError

    async def run(self) -> None:
        """Connect and keep reconnecting until close()."""
        raise NotImplementedError

    async def close(self) -> None:
        """Close the connection."""
        raise NotImplementedError

    @property
    def connected(self) -> bool:
        """Whether the handshake is done and the link is up."""
        raise NotImplementedError

    def on_state_change(self, callback: Callable[[bool], None]) -> Callable[[], None]:
        """Subscribe to connection state changes."""
        raise NotImplementedError

    def on_message(
        self,
        msg_type: str,
        callback: Callable[[HubMessage], Awaitable[None] | None],
    ) -> Callable[[], None]:
        """Subscribe to a message type."""
        raise NotImplementedError

    async def reply(
        self, request: HubMessage, msg_type: str, data: Mapping[str, Any]
    ) -> None:
        """Reply to a message, keeping its context."""
        raise NotImplementedError
