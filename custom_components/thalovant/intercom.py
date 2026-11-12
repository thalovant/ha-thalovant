"""Intercom: say a short text aloud on the hub's speakers.

Announce-only: a text of at most 280 characters, spoken by each chosen speaker's
own text to speech. It is a convenience, not a certified safety system. It does
not replace smoke or carbon monoxide alarms, medical alert devices or emergency
services, and it can fail silently: a speaker offline, a hub restarting, Do Not
Disturb, or a link that is down.

The rules this module keeps, because the text is spoken aloud in a home:

* Every announcement gets a fresh idempotency key. A key is never reused, so a
  second announcement with the same words is a second announcement.
* Nothing is retried. An error after the request left (a 502, a timeout) says
  that the announcement may still have been spoken, and names its id when the
  platform gave one.
* The text is never logged, stored, put in an event, a repair or an error.
  Home Assistant's own event bus and automation traces still hold the service
  data of the call that carried it; that is outside this integration.
* Everything is off until the options turn it on.
"""

import asyncio
from collections import deque
from collections.abc import Callable, Iterable, Mapping, Sequence
import re
import time
from typing import Any
import unicodedata
from uuid import uuid4

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .api import (
    Announcement,
    IntercomSpeakers,
    ThalovantApi,
    ThalovantAuthError,
    ThalovantConnectionError,
    ThalovantError,
    ThalovantHubLockedError,
    ThalovantHubUnreachableError,
    ThalovantIntercomUnavailableError,
    ThalovantNotASpeakerError,
    ThalovantNotCancellableError,
    ThalovantPlanError,
    ThalovantRateLimitedError,
    ThalovantSkillNotInstalledError,
    ThalovantTooManyTargetsError,
    ThalovantUrgentBusyError,
    ThalovantUrgentScopeRequiredError,
    Tokens,
)
from .const import (
    CONF_ALLOW_ANNOUNCEMENTS,
    CONF_ALLOW_URGENT,
    CONF_CREDENTIALS,
    CONF_HUB_ID,
    CONF_TOKENS,
    DOMAIN,
    EVENT_ANNOUNCEMENT_UPDATED,
    FOLLOW_GRACE,
    FOLLOW_INTERVAL,
    INTERCOM_SCOPES,
    INTERCOM_SEND_SCOPE,
    INTERCOM_URGENT_SCOPE,
    LOGGER,
    LOGIN_SCOPES,
    MAX_ANNOUNCEMENT_LENGTH,
    MAX_TARGET_NAME_LENGTH,
    MAX_TARGET_NAMES,
    MAX_WAIT,
    NORMAL_PER_MINUTE,
    SPEAKERS_TTL,
    STATUS_SENDING,
    URGENT_PER_HOUR,
)
from .handler import canonical_language
from .models import ThalovantConfigEntry

# The unicode categories no announcement may hold, as the platform's own rule
# has them: control (Cc), format (Cf: every bidirectional mark, the zero-width
# characters and the tag characters), lone surrogates (Cs), private use (Co)
# and the line and paragraph separators (Zl, Zp). The zero-width joiner and
# non-joiner are allowed: scripts and emoji sequences need them.
_UNSAFE_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Zl", "Zp"})
_JOINERS = frozenset("\u200c\u200d")
# Characters a text to speech engine that reads markup could take for it.
_MARKUP = frozenset("<>")
# A line break or a tab is a space, so a template's line breaks do not refuse a
# message. Nothing else is rewritten.
_BREAKS = re.compile(r"[\t\r\n]+")
_LANGUAGE = re.compile(r"[A-Za-z]{2,3}(?:[-_][A-Za-z0-9]{1,8}){0,3}")
_ANNOUNCEMENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")

# The repair issue's reasons, by what the platform or the settings said.
_ISSUE_REASONS = {
    "plan": "plan",
    "kid_hub": "kid_hub",
    "public_hub": "public_hub",
    "platform": "platform",
    "not_configured": "platform",
    "hub_off": "hub_off",
}

# The reasons an answer can give for Intercom being unavailable, each with its
# own error message.
_ERROR_REASONS = frozenset(
    {"hub_off", "kid_hub", "public_hub", "platform", "not_configured"}
)


class InvalidInputError(ValueError):
    """An announcement text, language or name Intercom will not send.

    reason names the rule: empty, too_long, markup, bad_characters, language,
    names.
    It never holds what was refused.
    """

    def __init__(self, reason: str) -> None:
        """Keep the rule that was broken."""
        super().__init__(reason)
        self.reason = reason


def collapse_whitespace(value: str) -> str:
    """White space of every kind becomes one space, and the ends are trimmed."""
    return " ".join(value.split())


def has_unsafe_characters(value: str) -> bool:
    """Whether value holds a control, format, private-use or separator character."""
    return any(unicodedata.category(char) in _UNSAFE_CATEGORIES for char in value)


def validate_text(text: str) -> str:
    """The text as it will be sent, or InvalidInputError.

    The platform's own rule, so a refusal costs no request: line breaks and tabs
    become spaces, then the text is NFC-normalised and trimmed and must be 1 to
    280 characters (counted after that), with no angle brackets, no control,
    bidirectional or other invisible format characters (the zero-width joiner
    and non-joiner are allowed), no lone surrogates, no private-use characters
    and no line or paragraph separators. Nothing is cut or stripped: a text that
    breaks a rule is refused, and the error never holds it.
    """
    lines = (line.strip(" ") for line in _BREAKS.split(text))
    cleaned = unicodedata.normalize("NFC", " ".join(line for line in lines if line))
    cleaned = cleaned.strip()
    if not cleaned:
        raise InvalidInputError("empty")
    if len(cleaned) > MAX_ANNOUNCEMENT_LENGTH:
        raise InvalidInputError("too_long")
    for char in cleaned:
        if char in _MARKUP:
            raise InvalidInputError("markup")
        if char not in _JOINERS and unicodedata.category(char) in _UNSAFE_CATEGORIES:
            raise InvalidInputError("bad_characters")
    return cleaned


def clean_received_text(text: str) -> str | None:
    """The text an announcement from the hub says, or None when it is unfit.

    The other direction: nothing is refused for its characters. Control, format
    and bidirectional characters are removed, and so are angle brackets, which a
    text to speech engine that reads markup could take for it. What is left is
    1 to 280 characters, or the announcement is ignored: it is never cut.
    """
    kept = "".join(
        " " if char in "<>" else char
        for char in text
        if char.isspace() or unicodedata.category(char) not in _UNSAFE_CATEGORIES
    )
    cleaned = collapse_whitespace(kept)
    if not cleaned or len(cleaned) > MAX_ANNOUNCEMENT_LENGTH:
        return None
    return cleaned


def validate_language(language: str) -> str:
    """A BCP 47 tag of the usual shape in its usual casing, or InvalidInputError."""
    tag = language.strip()
    if len(tag) > 35 or _LANGUAGE.fullmatch(tag) is None:
        raise InvalidInputError("language")
    return canonical_language(tag)


def validate_names(names: Iterable[str]) -> list[str]:
    """The names of speakers, rooms or groups to speak to, or InvalidInputError."""
    cleaned: list[str] = []
    for name in names:
        value = collapse_whitespace(name)
        if (
            not value
            or len(value) > MAX_TARGET_NAME_LENGTH
            or has_unsafe_characters(value)
        ):
            raise InvalidInputError("names")
        if value not in cleaned:
            cleaned.append(value)
    if len(cleaned) > MAX_TARGET_NAMES:
        raise InvalidInputError("names")
    return cleaned


def is_valid_announcement_id(value: str) -> bool:
    """Whether value can be an announcement's id: one safe path segment."""
    return _ANNOUNCEMENT_ID.fullmatch(value) is not None


def sanitize_label(value: str | None, limit: int = 80) -> str | None:
    """A label a household typed (a speaker's name), made safe to hand on.

    Control and format characters are removed and it is cut at limit, so a name
    cannot carry anything into an automation or a language model reading the
    response.
    """
    if value is None:
        return None
    kept = "".join(
        char
        for char in value
        if char.isspace() or unicodedata.category(char) not in _UNSAFE_CATEGORIES
    )
    return collapse_whitespace(kept)[:limit] or None


class SlidingWindowLimiter:
    """At most limit hits in any window seconds."""

    def __init__(
        self, limit: int, window: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        """Start empty."""
        self._limit = limit
        self._window = window
        self._clock = clock
        self._hits: deque[float] = deque()

    def allow(self) -> bool:
        """Count a hit if there is room for it, and say whether there was."""
        now = self._clock()
        while self._hits and now - self._hits[0] >= self._window:
            self._hits.popleft()
        if len(self._hits) >= self._limit:
            return False
        self._hits.append(now)
        return True


def scopes_for_options(options: Mapping[str, Any]) -> tuple[str, ...]:
    """The scopes a token needs for these options.

    LOGIN_SCOPES always; Intercom's only while announcements are on, and the
    urgent scope only while urgent announcements are. A link that has nothing
    turned on asks for exactly what it always did.
    """
    scopes = list(LOGIN_SCOPES)
    if options.get(CONF_ALLOW_ANNOUNCEMENTS) is True:
        scopes.extend(INTERCOM_SCOPES)
        if options.get(CONF_ALLOW_URGENT) is True:
            scopes.append(INTERCOM_URGENT_SCOPE)
    return tuple(scopes)


def unavailable_issue_id(entry_id: str) -> str:
    """The repair issue raised while Intercom cannot run on an entry's hub."""
    return f"intercom_unavailable_{entry_id}"


def can_play_issue_id(entry_id: str) -> str:
    """The repair issue raised while the platform was not told this link can play."""
    return f"intercom_can_play_{entry_id}"


class IntercomController:
    """Announce through one linked hub, as the account that linked it.

    Every call reads the entry's current token, because linking another hub
    with the same account replaces it for every entry. Nothing is cached about
    an announcement but its id, and nothing is sent that the options did not
    allow.
    """

    def __init__(self, hass: HomeAssistant, entry: ThalovantConfigEntry) -> None:
        """Prepare the limits; nothing is contacted."""
        self._hass = hass
        self._entry = entry
        self._normal = SlidingWindowLimiter(NORMAL_PER_MINUTE, 60.0)
        self._urgent = SlidingWindowLimiter(URGENT_PER_HOUR, 3600.0)
        self._speakers: tuple[float, IntercomSpeakers] | None = None
        self._followers: dict[str, asyncio.Task[Announcement]] = {}

    @property
    def announcements_allowed(self) -> bool:
        """Whether the options let this entry announce."""
        return self._entry.options.get(CONF_ALLOW_ANNOUNCEMENTS) is True

    def _scopes(self) -> frozenset[str]:
        """The scopes of the entry's current token; empty when it cannot be read."""
        try:
            return frozenset(Tokens.from_dict(self._entry.data[CONF_TOKENS]).scopes)
        except KeyError, TypeError, ValueError:
            return frozenset()

    @property
    def urgent_allowed(self) -> bool:
        """Whether urgent announcements are on, and the token may send them."""
        return (
            self.announcements_allowed
            and self._entry.options.get(CONF_ALLOW_URGENT) is True
            and INTERCOM_URGENT_SCOPE in self._scopes()
        )

    def _api(self) -> ThalovantApi:
        """The control plane with the entry's current token."""
        try:
            tokens = Tokens.from_dict(self._entry.data[CONF_TOKENS])
        except KeyError, TypeError, ValueError:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="token_unreadable",
                translation_placeholders={"hub": self._entry.title},
            ) from None
        return ThalovantApi(async_get_clientsession(self._hass), tokens)

    @property
    def _hub_id(self) -> str:
        hub_id: str = self._entry.data[CONF_HUB_ID]
        return hub_id

    def _fire(self, announcement: Announcement) -> None:
        """Tell automations an announcement's status: its id and status only."""
        self._hass.bus.async_fire(
            EVENT_ANNOUNCEMENT_UPDATED,
            {"announcement_id": announcement.id, "status": announcement.status},
        )

    def _error(self, err: ThalovantError, kind: str) -> HomeAssistantError:
        """The error a service call raises for what the platform answered.

        kind is announce, cancel or read. No message holds a text or a name.
        """
        placeholders: dict[str, str] = {"hub": self._entry.title}
        if isinstance(err, ThalovantNotCancellableError):
            placeholders["status"] = err.announcement_status or "unknown"
            return ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="not_cancellable",
                translation_placeholders=placeholders,
            )
        if isinstance(err, ThalovantNotASpeakerError):
            return ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="not_a_speaker",
                translation_placeholders=placeholders,
            )
        if isinstance(err, ThalovantTooManyTargetsError):
            return ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="too_many_targets",
                translation_placeholders=placeholders,
            )
        if isinstance(err, ThalovantRateLimitedError):
            retry = err.retry_after
            placeholders["seconds"] = (
                str(round(retry)) if retry is not None else "a few"
            )
            key = (
                "urgent_busy"
                if isinstance(err, ThalovantUrgentBusyError)
                else "rate_limited_remote"
            )
        elif isinstance(err, ThalovantUrgentScopeRequiredError):
            key = "urgent_scope_required"
        elif isinstance(err, ThalovantSkillNotInstalledError):
            key = "skill_not_installed"
        elif isinstance(err, ThalovantHubLockedError):
            key = "hub_locked"
        elif isinstance(err, ThalovantHubUnreachableError):
            placeholders["announcement"] = err.announcement_id or "unknown"
            key = "hub_unreachable"
        elif isinstance(err, ThalovantIntercomUnavailableError):
            self._async_update_issue(err.reason)
            reason = err.reason if err.reason in _ERROR_REASONS else "unknown"
            key = f"intercom_unavailable_{reason}"
        elif isinstance(err, ThalovantPlanError):
            key = "plan_limit"
        elif isinstance(err, ThalovantAuthError) and err.status in (401, 403):
            # 403 is a token without the permission; 401 is one Thalovant no
            # longer knows. (A locked account, 423, is neither: it is refused
            # below, with its status.)
            if err.status == 403:
                key = "scope_missing"
            else:
                self._entry.async_start_reauth(self._hass)
                key = "token_rejected"
        elif isinstance(err, ThalovantConnectionError):
            key = {
                "announce": "announce_outcome_unknown",
                "cancel": "cancel_outcome_unknown",
            }.get(kind, "cannot_reach_thalovant")
        elif err.status == 404 and kind == "cancel":
            return ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="announcement_not_found",
                translation_placeholders=placeholders,
            )
        elif err.status == 403 and "role required" in (err.detail or "").casefold():
            # A plain member of the account may read but not announce.
            key = "manager_required"
        else:
            placeholders["status"] = str(err.status or "unknown")
            placeholders["code"] = err.code or "unknown"
            key = "request_refused"
        return HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key=key,
            translation_placeholders=placeholders,
        )

    def _unexpected(self, err: Exception) -> HomeAssistantError:
        """An error nobody planned for: its type is logged, never its message."""
        LOGGER.warning("Intercom failed with %s", type(err).__name__)
        return HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="unexpected",
            translation_placeholders={"hub": self._entry.title},
        )

    def require_announcements(self) -> None:
        """Refuse clearly when the options have not turned announcements on."""
        if not self.announcements_allowed:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="announcements_disabled",
                translation_placeholders={"hub": self._entry.title},
            )
        if not set(INTERCOM_SCOPES) <= self._scopes():
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="scope_missing",
                translation_placeholders={"hub": self._entry.title},
            )

    async def async_announce(
        self,
        text: str,
        *,
        target: str = "all",
        names: Sequence[str] = (),
        priority: str = "normal",
        repeat: tuple[int, int] | None = None,
        lang: str | None = None,
        wait: bool = False,
    ) -> Announcement:
        """Make one announcement of text on the hub's speakers.

        text must already have gone through validate_text(). Raises
        ServiceValidationError for what the caller can fix and
        HomeAssistantError for what happened on the way; neither holds the
        text. Never retries, and never reuses an idempotency key.
        """
        self.require_announcements()
        urgent = priority == "urgent"
        if urgent and not self.urgent_allowed:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="urgent_disabled",
                translation_placeholders={"hub": self._entry.title},
            )
        if not (self._urgent if urgent else self._normal).allow():
            self._entry.runtime_data.intercom_stats.record_send_error(
                "rate_limited_local"
            )
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="rate_limited_urgent"
                if urgent
                else "rate_limited_normal",
                translation_placeholders={
                    "limit": str(URGENT_PER_HOUR if urgent else NORMAL_PER_MINUTE)
                },
            )

        targets: dict[str, object] = (
            {"all": True}
            if target == "all"
            else {
                target: await self._async_resolve(names, speakers=target == "speakers")
            }
        )
        api = self._api()
        stats = self._entry.runtime_data.intercom_stats
        try:
            announcement = await api.announce(
                self._hub_id,
                text,
                targets=targets,
                priority=priority,
                repeat=repeat,
                lang=lang,
                # One per call: a key is never shared by two announcements.
                idempotency_key=str(uuid4()),
            )
        except ValueError:
            # The SDK's own check of what was asked; its message never holds
            # the text, and neither does ours.
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_request",
                translation_placeholders={"hub": self._entry.title},
            ) from None
        except ThalovantError as err:
            stats.record_send_error(type(err).__name__)
            raise self._error(err, "announce") from err
        except Exception as err:  # noqa: BLE001 - a service call never crashes
            stats.record_send_error(type(err).__name__)
            raise self._unexpected(err) from None

        stats.record_sent(priority, announcement.status, dt_util.utcnow())
        self._fire(announcement)
        if announcement.status != STATUS_SENDING:
            return announcement
        budget = (repeat[0] * repeat[1] if repeat else 0) + FOLLOW_GRACE
        if wait:
            return await self._async_follow(announcement, min(budget, MAX_WAIT))
        task = self._entry.async_create_background_task(
            self._hass,
            self._async_follow(announcement, budget),
            name=f"{DOMAIN} follow announcement",
        )
        self._followers[announcement.id] = task
        task.add_done_callback(lambda _: self._followers.pop(announcement.id, None))
        return announcement

    async def _async_follow(
        self, announcement: Announcement, budget: float
    ) -> Announcement:
        """Read an announcement that is sending until it ends, or budget runs out.

        Fires the event at every change of status. A read that fails ends the
        following quietly: the announcement itself is unaffected.
        """
        current = announcement
        loop = asyncio.get_running_loop()
        deadline = loop.time() + budget
        while current.status == STATUS_SENDING:
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            await asyncio.sleep(min(FOLLOW_INTERVAL, remaining))
            try:
                read = await self._api().get_announcement(self._hub_id, current.id)
            except Exception as err:  # noqa: BLE001 - following is best effort
                LOGGER.debug(
                    "Could not follow announcement %s (%s)",
                    current.id,
                    type(err).__name__,
                )
                break
            if read.status != current.status:
                self._fire(read)
            current = read
        return current

    async def async_cancel(self, announcement_id: str) -> Announcement:
        """Stop an announcement that is still repeating.

        Allowed whatever the options say, once the token may send: turning
        announcements off must never leave an urgent one that cannot be
        stopped from here.
        """
        if INTERCOM_SEND_SCOPE not in self._scopes():
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="scope_missing",
                translation_placeholders={"hub": self._entry.title},
            )
        api = self._api()
        try:
            announcement = await api.cancel_announcement(self._hub_id, announcement_id)
        except ValueError:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_request",
                translation_placeholders={"hub": self._entry.title},
            ) from None
        except ThalovantError as err:
            raise self._error(err, "cancel") from err
        except Exception as err:  # noqa: BLE001 - a service call never crashes
            raise self._unexpected(err) from None
        if (task := self._followers.pop(announcement.id, None)) is not None:
            task.cancel()
        self._fire(announcement)
        return announcement

    async def async_list_speakers(self, *, fresh: bool = False) -> IntercomSpeakers:
        """The hub's speakers, from the platform (kept for a minute)."""
        self.require_announcements()
        now = time.monotonic()
        if not fresh and self._speakers and now - self._speakers[0] < SPEAKERS_TTL:
            return self._speakers[1]
        api = self._api()
        try:
            speakers = await api.list_intercom_speakers(self._hub_id)
        except ThalovantError as err:
            raise self._error(err, "read") from err
        except Exception as err:  # noqa: BLE001 - a service call never crashes
            raise self._unexpected(err) from None
        self._speakers = (now, speakers)
        return speakers

    async def _async_resolve(
        self, names: Sequence[str], *, speakers: bool
    ) -> list[str]:
        """What to send for the names a person typed.

        Rooms and groups go as typed. A speaker is its id or slug, and a person
        types its name as readily: a name that is exactly one speaker's becomes
        that speaker's slug, one that is several speakers' is refused, and one
        that is nobody's goes as typed for the platform to answer.
        """
        if not speakers:
            return list(names)
        try:
            known = await self.async_list_speakers()
        except HomeAssistantError:
            # The announcement's own request says what is wrong, precisely.
            return list(names)
        resolved: list[str] = []
        for name in names:
            folded = name.casefold()
            if any(name in (item.client_id, item.slug) for item in known.items):
                resolved.append(name)
                continue
            matches = [
                item
                for item in known.items
                if item.name and item.name.casefold() == folded
            ]
            if len(matches) > 1:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="ambiguous_speaker",
                    translation_placeholders={"hub": self._entry.title},
                )
            resolved.append(
                (matches[0].slug or matches[0].client_id) if matches else name
            )
        return resolved

    async def async_check_availability(self) -> None:
        """Raise or clear the repair issue about Intercom on this hub. Never raises.

        Intercom can be unavailable for the plan, because the hub is a kid or
        public hub, because the platform has it switched off, or because the
        hub's owner has not switched it on in the dashboard. Each says what to
        do, in a message of its own.
        """
        try:
            settings = await self._api().get_intercom_settings(self._hub_id)
        except Exception as err:  # noqa: BLE001 - a check never fails setup
            LOGGER.debug("Could not read Intercom's state (%s)", type(err).__name__)
            return
        if settings.unavailable_reason is not None:
            self._async_update_issue(settings.unavailable_reason)
        elif not settings.enabled:
            self._async_update_issue("hub_off")
        else:
            self.async_clear_issue()

    def _async_update_issue(self, reason: str) -> None:
        """Show why Intercom cannot run; a reason nobody knows is still shown."""
        ir.async_create_issue(
            self._hass,
            DOMAIN,
            unavailable_issue_id(self._entry.entry_id),
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=f"intercom_unavailable_{_ISSUE_REASONS.get(reason, 'unknown')}",
            translation_placeholders={"hub": self._entry.title},
        )

    def async_clear_issue(self) -> None:
        """Remove the repair issue about Intercom being unavailable."""
        ir.async_delete_issue(
            self._hass, DOMAIN, unavailable_issue_id(self._entry.entry_id)
        )

    async def async_set_can_play(self, can_play: bool) -> None:
        """Tell the platform whether this link can play announcements. Never raises.

        A failure leaves a repair issue, because the platform refuses receiving
        for a Home Assistant connection until it has been told.
        """
        issue_id = can_play_issue_id(self._entry.entry_id)
        try:
            await self._api().set_connection_can_play(
                self._entry.data[CONF_CREDENTIALS]["connection_id"], can_play
            )
        except Exception as err:  # noqa: BLE001 - never fails setup or an options save
            LOGGER.warning(
                "Could not tell Thalovant whether %s can play announcements (%s)",
                self._entry.title,
                type(err).__name__,
            )
            if can_play:
                ir.async_create_issue(
                    self._hass,
                    DOMAIN,
                    issue_id,
                    is_fixable=False,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key="intercom_can_play",
                    translation_placeholders={"hub": self._entry.title},
                )
            return
        ir.async_delete_issue(self._hass, DOMAIN, issue_id)
