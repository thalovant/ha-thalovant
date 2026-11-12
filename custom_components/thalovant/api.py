"""The integration's only door to the Thalovant SDK.

Nothing else in the integration imports the SDK. The types here are the
integration's own, in the shapes of the shared contract: config entries store
the to_dict() forms of Tokens and ConnectionCredentials, and the integration's
tests patch ThalovantAuth, ThalovantApi and HubConnection.

Underneath, each call goes to the async API of the ``thalovant`` SDK (0.12.0):
AsyncThalovantControlPlane for the control plane and AsyncHubSession for the
link to a hub. SDK objects are turned into the types below on the way out, and
SDK errors into the errors below. SDK_NAMES lists everything taken from it.
"""

from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
import importlib
import time
from types import MappingProxyType
from typing import Any, Final, Self, cast
from urllib.parse import quote

import aiohttp

SDK_MODULE: Final = "thalovant"

# Everything this file takes from the SDK, by name.
SDK_NAMES: Final = (
    "AsyncThalovantControlPlane",
    "AsyncHubSession",
    "ThalovantIdentity",
    "DeviceAuthorization",
    "HOME_ASSISTANT_CLIENT_ID",
    "hub_display_name",
    "ThalovantError",
    "ThalovantAPIError",
    "ThalovantAPIUnreachableError",
    "ThalovantAuthError",
    "ThalovantPlanError",
    "ThalovantAlreadyLinkedError",
    "ThalovantUnsupportedConnectionTypeError",
    "ThalovantConnectionError",
    "ThalovantHubRefusedError",
    "ThalovantClientKeyRejectedError",
    "ThalovantHubKeyChangedError",
    "ThalovantTimeoutError",
    "ThalovantAdmissionTimeoutError",
    "ThalovantAdmissionFailedError",
    "ThalovantIdentityError",
    "ThalovantDeviceLoginPending",
    "ThalovantDeviceLoginExpired",
    "ThalovantDeviceLoginDenied",
    "ThalovantIntercomDisabledError",
    "ThalovantIntercomUnavailableError",
    "ThalovantIntercomPlatformDisabledError",
    "ThalovantIntercomNotConfiguredError",
    "ThalovantUrgentScopeRequiredError",
    "ThalovantUrgentBusyError",
    "ThalovantSkillNotInstalledError",
    "ThalovantNotASpeakerError",
    "ThalovantTooManyTargetsError",
    "ThalovantHubLockedError",
    "ThalovantHubUnreachableError",
    "ThalovantRateLimitedError",
    "ThalovantNotCancellableError",
)

# Taken from thalovant.home: the speech rules every Thalovant SDK follows.
SDK_HOME_NAMES: Final = ("plain_speech",)

# Pages read from a hub listing before giving up on the rest.
MAX_PAGES: Final = 20


def _load_sdk() -> Any:
    """Import the SDK once, when Home Assistant imports this integration.

    Home Assistant installs it from the manifest's requirements first; the
    integration's tests run without it and patch the classes below.
    """
    try:
        return importlib.import_module(SDK_MODULE)
    except ImportError:
        return None


_sdk_module: Any = _load_sdk()


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
    """The API token, or the connection's credentials at the hub, were rejected."""


class ThalovantClientKeyRejectedError(ThalovantAuthError):
    """The hub refused this connection's own Noise key: it remembers another.

    A hub keeps the first key a connection shows it and refuses any other.
    This installation lost the key it linked with (a restore without
    .storage/thalovant, say), or another copy of it uses the same connection
    with its own key. No retry changes that; re-linking makes a new
    connection, which the hub meets afresh.
    """


class ThalovantConnectionError(ThalovantError):
    """Network, DNS, TLS, a 5xx or 429 answer, or a hub out of reach."""


class ThalovantHubKeyChangedError(ThalovantConnectionError):
    """The hub presented a different Noise key than the one pinned for it.

    The hub was replaced, or something sits between it and this installation;
    retrying cannot tell which. Only re-linking, which the user decides on,
    starts over with a new connection and a new pin.
    """


class ThalovantAdmissionTimeoutError(ThalovantConnectionError):
    """The hub had not admitted a new connection when the wait ran out."""


class ThalovantApiError(ThalovantError):
    """The API refused for a reason signing in again will not fix."""


class ThalovantAdmissionFailedError(ThalovantApiError):
    """The platform gave up admitting a new connection."""


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


class ThalovantRateLimitedError(ThalovantConnectionError):
    """The platform answered 429: nothing was done.

    A connection error, as a 429 always was, so existing callers treat it as
    "try later". retry_after is the number of seconds the API asked for.
    """

    def __init__(
        self,
        message: str = "",
        *,
        retry_after: float | None = None,
        status: int | None = None,
        code: str | None = None,
        detail: str | None = None,
    ) -> None:
        """Keep how long the API asked to wait."""
        super().__init__(message, status=status, code=code, detail=detail)
        self.retry_after = retry_after


class ThalovantHubUnreachableError(ThalovantConnectionError):
    """The platform could not reach the hub to speak (502 hub_unreachable).

    The text may or may not have been spoken: the hub can have spoken it and
    lost the answer. The platform records the attempt as a failed announcement
    and names it in announcement_id. Nothing may be sent again blindly.
    """

    def __init__(
        self,
        message: str = "",
        *,
        announcement_id: str | None = None,
        status: int | None = None,
        code: str | None = None,
        detail: str | None = None,
    ) -> None:
        """Keep the id of the announcement the platform recorded, when named."""
        super().__init__(message, status=status, code=code, detail=detail)
        self.announcement_id = announcement_id


class ThalovantUrgentBusyError(ThalovantRateLimitedError):
    """The hub (or the platform) already has its urgent announcements repeating.

    A 429 with the code intercom_urgent_busy: nothing was stored and nothing
    was spent. retry_after is how long the platform asked to wait.
    """


class ThalovantUrgentScopeRequiredError(ThalovantApiError):
    """An urgent announcement needs the intercom:urgent scope too (403).

    The platform checks it before it spends anything. It is not a rejected
    sign-in, so it never starts a re-authentication.
    """


class ThalovantSkillNotInstalledError(ThalovantApiError):
    """The hub has no Intercom skill yet (409), so an urgent one cannot be sent."""


class ThalovantNotASpeakerError(ThalovantApiError):
    """A connection that cannot play speech was named as a speaker (422)."""


class ThalovantTooManyTargetsError(ThalovantApiError):
    """The targets resolved to more than 50 speakers (422)."""


class ThalovantHubLockedError(ThalovantApiError):
    """The hub is locked (403 hub_locked): nothing was changed or sent."""


class ThalovantIntercomUnavailableError(ThalovantApiError):
    """Intercom cannot be used here.

    reason is hub_off (the hub's switch is off), kid_hub or public_hub (never
    available there), platform (the platform's own switch is off, which is how
    Intercom ships until it is rolled out), not_configured (the platform is not
    set up for it yet) or unknown (a reason this version does not know).
    """

    def __init__(
        self,
        message: str = "",
        *,
        reason: str,
        status: int | None = None,
        code: str | None = None,
        detail: str | None = None,
    ) -> None:
        """Keep why Intercom is unavailable."""
        super().__init__(message, status=status, code=code, detail=detail)
        self.reason = reason


class ThalovantNotCancellableError(ThalovantApiError):
    """Only an announcement that is still sending can be cancelled (409)."""

    def __init__(
        self,
        message: str = "",
        *,
        announcement_status: str | None = None,
        status: int | None = None,
        code: str | None = None,
        detail: str | None = None,
    ) -> None:
        """Keep the status the announcement has now, when the API says."""
        super().__init__(message, status=status, code=code, detail=detail)
        self.announcement_status = announcement_status


class DeviceLoginPending(ThalovantError):
    """Not approved yet; poll again after interval seconds."""

    def __init__(self, message: str = "", *, interval: float) -> None:
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

    device_code: str = field(repr=False)
    user_code: str
    verification_uri: str
    verification_uri_complete: str | None
    interval: float
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


def _optional_text(value: Any) -> str | None:
    """A string with something in it, or None."""
    return value.strip() or None if isinstance(value, str) else None


def _can_link(item: Mapping[str, Any]) -> bool | None:
    """Read capabilities.home_assistant from a hub; None when it is not a bool."""
    capabilities = item.get("capabilities")
    if not isinstance(capabilities, Mapping):
        return None
    value = capabilities.get("home_assistant")
    return value if isinstance(value, bool) else None


@dataclass(frozen=True, slots=True)
class Tokens:
    """The API token from a device login. The form stored in the entry.

    There is no refresh token: a device-login token lives a year. token_id is
    what revokes it.
    """

    access_token: str = field(repr=False)
    expires_at: datetime | None
    scopes: tuple[str, ...]
    token_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe form."""
        return {
            "access_token": self.access_token,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "scopes": list(self.scopes),
            "token_id": self.token_id,
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
            expires_at=datetime.fromisoformat(expires_at) if expires_at else None,
            scopes=tuple(scopes),
            token_id=_text(data, "token_id", optional=True),
        )


@dataclass(frozen=True, slots=True)
class Account:
    """The signed-in Thalovant account."""

    id: str
    display_name: str | None
    email: str | None


@dataclass(frozen=True, slots=True)
class Hub:
    """A hub the account may link: its own hubs, then the public ones."""

    id: str
    name: str
    # Whether the hub can pass requests to Home Assistant, from the API's
    # capabilities.home_assistant; None when the API does not say.
    can_link: bool | None = None


@dataclass(frozen=True, slots=True)
class IntercomSettings:
    """Whether Intercom can run on a hub, from GET .../intercom/settings.

    unavailable_reason is plan, kid_hub, public_hub or platform when it cannot;
    None when it can.
    """

    enabled: bool
    plan_allowed: bool
    unavailable_reason: str | None


@dataclass(frozen=True, slots=True)
class IntercomSpeaker:
    """A connection of the hub that may be spoken to, with its policy.

    kind is the connection's kind (voice_satellite, web_chat, developer,
    embedded, home_assistant). can_play is the platform's effective answer to
    "can it play speech at all": a connection that cannot is listed, but it
    cannot receive and is never part of every speaker, a room or a group. A
    Home Assistant connection can only once it says so (see
    ThalovantApi.set_connection_can_play).
    """

    client_id: str
    slug: str | None
    name: str | None
    online: bool
    receive: bool
    room: str | None
    groups: tuple[str, ...]
    kind: str = "voice_satellite"
    can_play: bool = True


@dataclass(frozen=True, slots=True)
class IntercomSpeakers:
    """The hub's speakers, from GET .../intercom/speakers.

    policy_synced is False while the hub may hold an out of date consent map
    (a change may take a moment to reach it); None when the platform does not
    say. unavailable_reason is the platform's reason Intercom cannot run
    (platform, plan, kid_hub, public_hub), or None.
    """

    items: tuple[IntercomSpeaker, ...]
    policy_synced: bool | None = None
    unavailable_reason: str | None = None


@dataclass(frozen=True, slots=True)
class Announcement:
    """An announcement as the platform reports it. It never holds the text.

    deliveries is the status of each speaker's delivery. hub_confirmed is set
    only by a cancel: False means the hub could not confirm that it stopped, so
    speech already queued on it may still play. replayed is True when the
    platform answered with an announcement it had already stored for the same
    idempotency key, so nothing new was sent.
    """

    id: str
    status: str
    priority: str
    deliveries: tuple[str, ...]
    acked_by: str | None
    hub_confirmed: bool | None
    replayed: bool = False

    @property
    def delivery_counts(self) -> dict[str, int]:
        """How many deliveries have each status."""
        return dict(Counter(self.deliveries))


@dataclass(frozen=True, slots=True)
class ConnectionCredentials:
    """What reaches a hub. The form stored in the entry; secret is opaque."""

    hub_id: str
    connection_id: str
    name: str
    endpoint: str
    secret: Mapping[str, Any] = field(repr=False, hash=False)
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
        if not isinstance(secret, Mapping) or not secret:
            raise ValueError("secret is missing")
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
    """A message from the hub. Reply to it with HubConnection.reply().

    received_at is when it arrived, on the monotonic clock: the hub's time
    limit for an answer counts from there.
    """

    type: str
    data: Mapping[str, Any]
    context: Mapping[str, Any]
    sdk: Any = field(default=None, repr=False, compare=False)
    received_at: float = field(default_factory=time.monotonic, compare=False)


def _sdk(name: str) -> Any:
    """Return one of SDK_NAMES from the installed SDK."""
    if _sdk_module is None:
        raise ThalovantError("The thalovant SDK is not installed")
    try:
        return getattr(_sdk_module, name)
    except AttributeError as err:
        raise ThalovantError(f"The installed thalovant SDK has no {name}") from err


def plain_speech(text: str | None) -> str:
    """Speech a device can say as it is: markup removed, references decoded.

    The SDK's rules, shared by every Thalovant SDK: only real tags go, only
    numeric references, the five XML entities and &nbsp; are decoded, and
    Unicode white space collapses to single spaces.
    """
    if _sdk_module is None:
        raise ThalovantError("The thalovant SDK is not installed")
    home = importlib.import_module(f"{SDK_MODULE}.home")
    return str(home.plain_speech(text))


def _is(err: BaseException, name: str) -> bool:
    """Whether err is an instance of the SDK class called name."""
    cls = getattr(_sdk_module, name, None)
    return isinstance(cls, type) and isinstance(err, cls)


def _translate(err: Exception) -> ThalovantError | None:
    """Turn an SDK error into ours; None for anything that is not one.

    Most specific first: several SDK errors derive from ThalovantAPIError or
    ThalovantConnectionError.
    """
    message = str(err)
    facts: dict[str, Any] = {
        "status": getattr(err, "status_code", None),
        "code": getattr(err, "code", None),
        "detail": getattr(err, "detail", None),
    }
    if _is(err, "ThalovantDeviceLoginPending"):
        return DeviceLoginPending(message, interval=float(getattr(err, "interval", 0)))
    if _is(err, "ThalovantDeviceLoginExpired"):
        return DeviceLoginExpired(message, **facts)
    if _is(err, "ThalovantDeviceLoginDenied"):
        return DeviceLoginDenied(message, **facts)
    if _is(err, "ThalovantHubKeyChangedError"):
        return ThalovantHubKeyChangedError(message)
    if _is(err, "ThalovantClientKeyRejectedError"):
        # A refusal too (the SDK's class derives from it), but one that names
        # the cause: checked first.
        return ThalovantClientKeyRejectedError(message)
    if _is(err, "ThalovantHubRefusedError"):
        # A connection error in the SDK; for the integration it means the
        # credentials, so reauthentication (after the admission grace).
        return ThalovantAuthError(message)
    if _is(err, "ThalovantAdmissionTimeoutError"):
        return ThalovantAdmissionTimeoutError(message)
    if _is(err, "ThalovantAdmissionFailedError"):
        # The platform's own failure has an error_code and no status; a refusal
        # of the wait keeps what the API answered.
        return ThalovantAdmissionFailedError(
            message,
            status=facts["status"],
            code=getattr(err, "error_code", None) or facts["code"],
            detail=facts["detail"],
        )
    if _is(err, "ThalovantAPIUnreachableError"):
        # DNS, TCP, TLS or a timeout: the API never answered.
        return ThalovantConnectionError(message)
    # Before the sign-in errors: the SDK's "urgent scope required" is a kind of
    # ThalovantAuthError, but it is not a rejected sign-in.
    if (intercom := _translate_intercom(err, message, facts)) is not None:
        return intercom
    if _is(err, "ThalovantAuthError"):
        return ThalovantAuthError(message, **facts)
    if _is(err, "ThalovantPlanError"):
        return ThalovantPlanError(message, **facts)
    if _is(err, "ThalovantAlreadyLinkedError"):
        return ThalovantAlreadyLinkedError(
            message, connection_id=getattr(err, "client_id", None), **facts
        )
    if _is(err, "ThalovantUnsupportedConnectionTypeError"):
        return ThalovantUnsupportedError(message, **facts)
    if _is(err, "ThalovantConnectionError") or _is(err, "ThalovantTimeoutError"):
        return ThalovantConnectionError(message)
    if _is(err, "ThalovantAPIError"):
        status = facts["status"]
        # The API answered, but 429 and 5xx pass with time.
        if status is not None and (status == 429 or status >= 500):
            return ThalovantConnectionError(message, **facts)
        return ThalovantApiError(message, **facts)
    if _is(err, "ThalovantError"):
        return ThalovantError(message)
    return None


# The reasons a 422 intercom_unavailable gives. Anything else is "unknown".
_NEVER_AVAILABLE: Final = frozenset({"kid_hub", "public_hub"})


def _fact(err: Exception, key: str) -> Any:
    """What the answer says under key: the SDK error's own property, else its problem body.

    The problem body is read at its top and inside an object detail, where
    FastAPI wraps a structured refusal.
    """
    value = getattr(err, key, None)
    if value is None:
        problem = getattr(err, "problem", None)
        if isinstance(problem, Mapping):
            detail = problem.get("detail")
            value = problem.get(key)
            if value is None and isinstance(detail, Mapping):
                value = detail.get(key)
    return value


def _problem_text(err: Exception, key: str) -> str | None:
    """A text fact of the answer, or None."""
    return _optional_text(_fact(err, key))


def _unavailable_reason(err: Exception, code: str | None) -> str | None:
    """Why Intercom is unavailable, when the answer says it is; None otherwise.

    By the problem's code, then by the SDK's class: the platform's own switch
    (a hub's own switch cannot change it), a platform that is not set up, a kid
    or public hub (the problem's reason names which), or the hub's own switch.
    """
    if code == "intercom_disabled_platform" or _is(
        err, "ThalovantIntercomPlatformDisabledError"
    ):
        return "platform"
    if code == "intercom_not_configured" or _is(
        err, "ThalovantIntercomNotConfiguredError"
    ):
        return "not_configured"
    if code == "intercom_unavailable" or _is(err, "ThalovantIntercomUnavailableError"):
        reason = _problem_text(err, "reason")
        return reason if reason in _NEVER_AVAILABLE else "unknown"
    if code == "intercom_disabled" or _is(err, "ThalovantIntercomDisabledError"):
        return "hub_off"
    return None


def _translate_intercom(
    err: Exception, message: str, facts: dict[str, Any]
) -> ThalovantError | None:
    """Turn an SDK error that Intercom answers with into ours, or None.

    By class and by the problem's code, so an answer the SDK has no class for
    still reaches the right message. Most specific first: the urgent pool's 429
    is a kind of 429, and the platform's switch a kind of "Intercom is off".
    """
    status, code = facts["status"], facts["code"]
    if _is(err, "ThalovantUrgentScopeRequiredError") or code == "urgent_scope_required":
        return ThalovantUrgentScopeRequiredError(message, **facts)
    if status == 429 or _is(err, "ThalovantRateLimitedError"):
        retry_after = getattr(err, "retry_after_seconds", None)
        retry = float(retry_after) if isinstance(retry_after, (int, float)) else None
        if _is(err, "ThalovantUrgentBusyError") or code == "intercom_urgent_busy":
            return ThalovantUrgentBusyError(message, retry_after=retry, **facts)
        return ThalovantRateLimitedError(message, retry_after=retry, **facts)
    if _is(err, "ThalovantHubUnreachableError") or (
        status == 502 and code == "hub_unreachable"
    ):
        return ThalovantHubUnreachableError(
            message,
            announcement_id=_problem_text(err, "announcement_id"),
            **facts,
        )
    if _is(err, "ThalovantNotCancellableError") or code == "not_cancellable":
        return ThalovantNotCancellableError(
            message,
            announcement_status=_problem_text(err, "announcement_status"),
            **facts,
        )
    if _is(err, "ThalovantSkillNotInstalledError") or code == "skill_not_installed":
        return ThalovantSkillNotInstalledError(message, **facts)
    if _is(err, "ThalovantNotASpeakerError") or code == "not_a_speaker":
        return ThalovantNotASpeakerError(message, **facts)
    if _is(err, "ThalovantTooManyTargetsError") or code == "too_many_targets":
        return ThalovantTooManyTargetsError(message, **facts)
    if _is(err, "ThalovantHubLockedError") or code == "hub_locked":
        return ThalovantHubLockedError(message, **facts)
    if (reason := _unavailable_reason(err, code)) is not None:
        return ThalovantIntercomUnavailableError(message, reason=reason, **facts)
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


def _control_plane(
    session: aiohttp.ClientSession,
    *,
    api_url: str | None,
    access_token: str | None = None,
) -> Any:
    """An SDK control plane over Home Assistant's session."""
    args = (api_url,) if api_url else ()
    return _sdk("AsyncThalovantControlPlane")(
        *args, access_token=access_token, session=session
    )


async def _pages(
    fetch: Callable[[str | None], Awaitable[Mapping[str, Any]]],
) -> list[Mapping[str, Any]]:
    """Every item of a paginated listing ({"data": [...], "meta": {"next": ...}})."""
    items: list[Mapping[str, Any]] = []
    cursor: str | None = None
    for _ in range(MAX_PAGES):
        body = await fetch(cursor)
        data = body.get("data")
        if isinstance(data, list):
            items.extend(item for item in data if isinstance(item, Mapping))
        meta = body.get("meta")
        cursor = _optional_text(meta.get("next")) if isinstance(meta, Mapping) else None
        if cursor is None:
            break
    return items


class ThalovantAuth:
    """Device login against the control plane."""

    def __init__(
        self, session: aiohttp.ClientSession, *, api_url: str | None = None
    ) -> None:
        """Use Home Assistant's shared session."""
        self._session = session
        self._api_url = api_url
        self._plane: Any = None

    def _control(self) -> Any:
        # One plane for every poll: it remembers each slow_down.
        if self._plane is None:
            self._plane = _control_plane(self._session, api_url=self._api_url)
        return self._plane

    async def start_device_login(
        self, *, client_name: str, scopes: Sequence[str]
    ) -> DeviceLogin:
        """Ask for a device code, as the registered Home Assistant app.

        The approval page then names the request Home Assistant, marked as an
        app Thalovant knows, with client_name beside it as this installation's
        own label. Approving it replaces the token the app already held for
        the account instead of counting a second one against the plan.
        """
        async with _translated():
            grant = await self._control().begin_device_login(
                scopes=list(scopes),
                client_name=client_name,
                client_id=_sdk("HOME_ASSISTANT_CLIENT_ID"),
            )
        return DeviceLogin(
            device_code=grant.device_code,
            user_code=grant.user_code,
            verification_uri=grant.verification_uri,
            verification_uri_complete=grant.verification_uri_complete,
            interval=float(grant.interval),
            expires_in=int(grant.expires_in),
            sdk=grant,
        )

    async def poll_device_login(self, login: DeviceLogin) -> Tokens:
        """Poll once: the tokens, or DeviceLoginPending, Expired or Denied."""
        async with _translated():
            grant = login.sdk
            if grant is None:
                grant = _sdk("DeviceAuthorization")(
                    device_code=login.device_code,
                    user_code=login.user_code,
                    verification_uri=login.verification_uri,
                    verification_uri_complete=login.verification_uri_complete,
                    interval=login.interval,
                    expires_in=login.expires_in,
                )
            token = await self._control().poll_device_login(grant)
        return Tokens(
            access_token=token.access_token,
            expires_at=token.expires_at,
            scopes=tuple(token.scopes),
            token_id=token.token_id,
        )


class ThalovantApi:
    """The control plane, as the signed-in account."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        tokens: Tokens,
        *,
        api_url: str | None = None,
    ) -> None:
        """Use Home Assistant's shared session and the account's token."""
        self._session = session
        self._tokens = tokens
        self._api_url = api_url
        self._plane: Any = None
        self._account_id: str | None = None

    def _control(self) -> Any:
        if self._plane is None:
            self._plane = _control_plane(
                self._session,
                api_url=self._api_url,
                access_token=self._tokens.access_token,
            )
            # The token's own id: revoking it then counts a token that is
            # already dead (a 401) as revoked, which is what it is.
            self._plane.token_id = self._tokens.token_id
        return self._plane

    async def get_account(self) -> Account:
        """Return the signed-in account."""
        async with _translated():
            profile = await self._control().get_profile()
        account_id = _optional_text(profile.get("id"))
        if account_id is None:
            raise ThalovantApiError("The Thalovant profile carried no account id")
        self._account_id = account_id
        return Account(
            id=account_id,
            display_name=_optional_text(profile.get("display_name")),
            email=_optional_text(profile.get("email")),
        )

    async def list_hubs(self) -> list[Hub]:
        """Return the hubs this account may link: its own, then the public ones.

        The own hubs are asked for by owner, because an administrator's token
        otherwise lists every tenant's. Locked hubs take no new connection.
        """
        owner = self._account_id or (await self.get_account()).id
        control = self._control()
        display_name = _sdk("hub_display_name")
        hubs: dict[str, Hub] = {}
        async with _translated():
            own = await _pages(
                lambda cursor: control.list_hubs(owner_id=owner, cursor=cursor)
            )
            public = await _pages(
                lambda cursor: control.list_public_hubs(cursor=cursor)
            )
        for item in own:
            hub_id = _optional_text(item.get("id"))
            if hub_id and item.get("is_locked") is not True:
                hubs.setdefault(
                    hub_id,
                    Hub(id=hub_id, name=display_name(item), can_link=_can_link(item)),
                )
        for item in public:
            hub_id = _optional_text(item.get("id"))
            if hub_id:
                name = _optional_text(item.get("title")) or display_name(item)
                hubs.setdefault(
                    hub_id, Hub(id=hub_id, name=name, can_link=_can_link(item))
                )
        return list(hubs.values())

    async def create_connection(
        self, hub_id: str, *, name: str, kind: str
    ) -> ConnectionCredentials:
        """Create this installation's connection on a hub, of the given kind."""
        async with _translated():
            result = await self._control().create_client_identity(
                hub_id, name=name, connection_type=kind
            )
        connection_id = _optional_text(result.client_id)
        if connection_id is None:
            raise ThalovantApiError("The connection was created without an id")
        identity = result.identity
        operation = result.operation
        return ConnectionCredentials(
            hub_id=hub_id,
            connection_id=connection_id,
            name=name,
            endpoint=getattr(result.endpoint, "endpoint", None)
            or identity.default_master,
            secret=identity.as_dict(include_secrets=True),
            operation_url=(
                (operation.links.get("self") or operation.id) if operation else None
            ),
        )

    async def wait_for_admission(
        self, credentials: ConnectionCredentials, *, timeout: float
    ) -> None:
        """Return once the hub has admitted the connection, or nothing tracks it."""
        async with _translated():
            await self._control().wait_for_admission(
                credentials.operation_url, timeout=timeout
            )

    async def delete_connection(self, connection_id: str) -> None:
        """Delete a connection; one already gone counts as deleted."""
        async with _translated():
            await self._control().delete_client(connection_id)

    async def revoke_token(self) -> None:
        """Revoke the API token this client signs in with; one already dead counts."""
        if self._tokens.token_id is None:
            raise ThalovantApiError("The stored API token has no id to revoke it by")
        async with _translated():
            await self._control().revoke_api_token(self._tokens.token_id)

    async def get_intercom_settings(self, hub_id: str) -> IntercomSettings:
        """Read whether Intercom can run on a hub (needs intercom:read)."""
        async with _translated():
            settings = await self._control().get_intercom_settings(hub_id)
        return IntercomSettings(
            enabled=settings.enabled is True,
            plan_allowed=settings.plan_allowed is True,
            unavailable_reason=_optional_text(settings.unavailable_reason),
        )

    async def list_intercom_speakers(self, hub_id: str) -> IntercomSpeakers:
        """Read the hub's speakers and their policies (needs intercom:read)."""
        async with _translated():
            listing = await self._control().list_intercom_speakers(hub_id)
        synced = getattr(listing, "policy_synced", None)
        return IntercomSpeakers(
            items=tuple(
                IntercomSpeaker(
                    client_id=item.client_id,
                    slug=item.slug,
                    name=item.name,
                    online=item.online is True,
                    receive=item.intercom.receive is True,
                    room=item.intercom.room,
                    groups=tuple(item.intercom.groups),
                    kind=_optional_text(getattr(item, "kind", None))
                    or "voice_satellite",
                    # The platform's own default is "can play": only an explicit
                    # false says it cannot.
                    can_play=getattr(item, "can_play", True) is not False,
                )
                for item in listing.items
            ),
            policy_synced=synced if isinstance(synced, bool) else None,
            unavailable_reason=_optional_text(
                getattr(listing, "unavailable_reason", None)
            ),
        )

    async def announce(
        self,
        hub_id: str,
        text: str,
        *,
        targets: Mapping[str, Any],
        priority: str,
        repeat: tuple[int, int] | None,
        lang: str | None,
        idempotency_key: str,
    ) -> Announcement:
        """Say text on the hub's speakers (needs intercom:send). Never retries.

        One request: the SDK does not retry, and neither does this. text goes
        to the SDK and nowhere else: no log, no error and no return value holds
        it. repeat is (times, interval in seconds) for an urgent announcement.
        """
        async with _translated():
            announcement = await self._control().announce(
                hub_id,
                text,
                dict(targets),
                priority=priority,
                repeat=(
                    {"times": repeat[0], "interval_seconds": repeat[1]}
                    if repeat
                    else None
                ),
                lang=lang,
                idempotency_key=idempotency_key,
            )
        return _announcement(announcement)

    async def get_announcement(self, hub_id: str, announcement_id: str) -> Announcement:
        """Read one announcement (needs intercom:read)."""
        async with _translated():
            announcement = await self._control().get_announcement(
                hub_id, announcement_id
            )
        return _announcement(announcement)

    async def cancel_announcement(
        self, hub_id: str, announcement_id: str
    ) -> Announcement:
        """Stop an announcement that is still repeating (needs intercom:send)."""
        async with _translated():
            announcement = await self._control().cancel_announcement(
                hub_id, announcement_id
            )
        return _announcement(announcement)

    async def set_connection_can_play(self, connection_id: str, can_play: bool) -> None:
        """Tell the platform whether this connection can play announcements.

        Declares spec.intercom.can_play on the connection. A Home Assistant
        connection cannot be a speaker, and its owner cannot switch receiving on
        for it, until it says it can; with it false again, it is not one.

        SDK GAP: SDK 0.12.0 has no call that updates a connection, so this is the
        one place the integration reaches for the SDK's private _request(). It
        reads the connection with the public get_client() and writes it back as
        PATCH /v1/clients/{id} wants it (clients:write): the whole spec, with the
        etag as If-Match. The one thing a caller may say under spec.intercom is
        can_play, so that is all that is sent there; the platform keeps the rest
        of it. A change made between the read and the write is a 412, and the
        read-and-write is tried once more. Replace this with the SDK's own
        method once it has one; tests/test_api_intercom_sdk.py checks it
        against the real SDK, so a release that moves _request fails there.
        """
        control = self._control()
        request = getattr(control, "_request", None)
        if request is None:
            raise ThalovantError(
                "The installed thalovant SDK cannot update a connection"
            )
        path = f"/v1/clients/{quote(connection_id, safe='')}"
        async with _translated():
            attempt = 0
            while True:
                client = await control.get_client(connection_id)
                spec = client.get("spec") if isinstance(client, Mapping) else None
                etag = client.get("etag") if isinstance(client, Mapping) else None
                if (
                    not isinstance(spec, Mapping)
                    or not isinstance(etag, str)
                    or not etag
                ):
                    raise ThalovantApiError(
                        "The connection came without a spec or an etag"
                    )
                intercom = spec.get("intercom")
                if (
                    isinstance(intercom, Mapping)
                    and intercom.get("can_play") is can_play
                ):
                    return
                body = {"spec": {**spec, "intercom": {"can_play": can_play}}}
                try:
                    await request("PATCH", path, json=body, headers={"If-Match": etag})
                except Exception as err:
                    if attempt == 0 and getattr(err, "status_code", None) == 412:
                        attempt += 1
                        continue
                    raise
                return


def _announcement(result: Any) -> Announcement:
    """Our Announcement from the SDK's. It has no text to leave behind."""
    return Announcement(
        id=result.id,
        status=str(result.status),
        priority=str(result.priority),
        deliveries=tuple(str(delivery.status) for delivery in result.deliveries),
        acked_by=_optional_text(result.acked_by),
        hub_confirmed=result.hub_confirmed
        if isinstance(result.hub_confirmed, bool)
        else None,
        replayed=getattr(result, "replayed", False) is True,
    )


class HubConnection:
    """The outbound link to one hub."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        credentials: ConnectionCredentials,
        *,
        state_dir: str | None = None,
        self_hosted: bool = False,
    ) -> None:
        """Prepare the link. Raises ValueError if the credentials are unusable.

        state_dir holds this installation's Noise static key, which the hub
        pins on first contact, so it must outlive restarts and updates.
        """
        try:
            identity = _sdk("ThalovantIdentity").from_mapping(credentials.secret)
        except Exception as err:
            if _is(err, "ThalovantIdentityError"):
                raise ValueError(
                    "The stored connection credentials are unusable"
                ) from err
            raise
        options = {"protocol": "wss", "self_signed": False} if self_hosted else {}
        if self_hosted and identity.endpoint_for("wss") != credentials.endpoint:
            raise ValueError("Private hub identity does not match its endpoint")
        self._self_hosted = self_hosted
        self._link = _sdk("AsyncHubSession").for_identity(
            identity, session=session, noise_state_dir=state_dir, **options
        )

    @property
    def connected(self) -> bool:
        """Whether the link is up."""
        return bool(self._link.connected)

    async def connect(self) -> None:
        """Make one attempt; raises ThalovantAuthError or ThalovantConnectionError."""
        async with _translated():
            await self._link.connect()

    async def run(self) -> None:
        """Stay connected until close(); raises ThalovantAuthError once refused for good."""
        async with _translated():
            await self._link.run()

    async def close(self) -> None:
        """Close the link."""
        async with _translated():
            await self._link.close()

    def on_state_change(self, callback: Callable[[bool], None]) -> Callable[[], None]:
        """Call back with the new state on every change; returns the unsubscribe."""
        return cast(Callable[[], None], self._link.on_state_change(callback))

    def on_message(
        self, msg_type: str, callback: Callable[[HubMessage], None]
    ) -> Callable[[], None]:
        """Call back for every message of one type; returns the unsubscribe."""

        def relay(event: Any) -> None:
            context = event.context
            if self._self_hosted:
                # The SDK rewrites source to this node's address on delivery.
                # Private admission must use the original authenticated sender.
                wire_context = getattr(event.raw, "wire_context", None)
                context = wire_context if isinstance(wire_context, Mapping) else {}
            callback(
                HubMessage(type=event.name, data=event.data, context=context, sdk=event)
            )

        return cast(Callable[[], None], self._link.on(msg_type, relay))

    async def reply(
        self, request: HubMessage, msg_type: str, data: Mapping[str, Any]
    ) -> None:
        """Answer a message, keeping its context, session and routing."""
        async with _translated():
            await self._link.reply(request.sdk, msg_type, dict(data))
