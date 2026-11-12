"""Runtime data for the Thalovant integration."""

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform

from .api import HubConnection

if TYPE_CHECKING:
    from .intercom import IntercomController


@dataclass(slots=True)
class RequestStats:
    """Counts of handled requests, kept for diagnostics.

    Only outcomes are recorded: never an utterance, a reply, or a conversation id.
    """

    handled: int = 0
    outcomes: Counter[str] = field(default_factory=Counter)
    last_outcome: str | None = None
    last_handled_at: datetime | None = None
    last_duration_ms: int | None = None

    def record(self, outcome: str, handled_at: datetime, duration_ms: int) -> None:
        """Record one answered request."""
        self.handled += 1
        self.outcomes[outcome] += 1
        self.last_outcome = outcome
        self.last_handled_at = handled_at
        self.last_duration_ms = duration_ms


@dataclass(slots=True)
class IntercomStats:
    """Counts of announcements, kept for diagnostics.

    Only counts and outcomes are recorded: never a text, a target, a speaker's
    name, a player or an announcement's id.
    """

    sent: Counter[str] = field(default_factory=Counter)
    send_outcomes: Counter[str] = field(default_factory=Counter)
    received: Counter[str] = field(default_factory=Counter)
    last_sent_at: datetime | None = None
    last_received_at: datetime | None = None

    def record_sent(self, priority: str, outcome: str, sent_at: datetime) -> None:
        """Record one announcement made, with the status the platform gave it."""
        self.sent[priority] += 1
        self.send_outcomes[outcome] += 1
        self.last_sent_at = sent_at

    def record_send_error(self, outcome: str) -> None:
        """Record an announcement that was refused or whose outcome is unknown."""
        self.send_outcomes[outcome] += 1

    def record_received(self, outcome: str, received_at: datetime) -> None:
        """Record what became of one announcement the hub asked this Home Assistant to play."""
        self.received[outcome] += 1
        self.last_received_at = received_at


@dataclass(slots=True)
class ThalovantRuntimeData:
    """What a loaded entry holds."""

    connection: HubConnection
    stats: RequestStats = field(default_factory=RequestStats)
    intercom_stats: IntercomStats = field(default_factory=IntercomStats)
    # None for a private (self-hosted) link, which has no account to announce as.
    intercom: IntercomController | None = None
    # What async_forward_entry_setups was given, so unloading undoes exactly that
    # whatever the options say by then.
    platforms: list[Platform] = field(default_factory=list)
    # The Intercom options as they were at setup: a change to any of them reloads.
    intercom_options: dict[str, Any] = field(default_factory=dict)


type ThalovantConfigEntry = ConfigEntry[ThalovantRuntimeData]
