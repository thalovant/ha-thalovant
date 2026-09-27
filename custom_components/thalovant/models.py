"""Runtime data for the Thalovant integration."""

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from aiothalovant import HubConnection

from homeassistant.config_entries import ConfigEntry


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
class ThalovantRuntimeData:
    """What a loaded entry holds."""

    connection: HubConnection
    stats: RequestStats = field(default_factory=RequestStats)


type ThalovantConfigEntry = ConfigEntry[ThalovantRuntimeData]
