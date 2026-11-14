"""Look after the names and rooms of the Music Assistant players Assist may use.

"Play jazz in the kitchen" finds a speaker by its room, and "play jazz on Kitchen" by its
name. Two things silently break that, and Home Assistant says nothing about either: an
exposed Music Assistant player with no area, and two exposed media players with the same
spoken name (a Chromecast and a Music Assistant player both called "Kitchen"). This module
raises a repair issue for each (a warning, never fixable: the person fixes it in Home
Assistant's own device page) and clears it when the registries say it is fixed.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, State, callback
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.start import async_at_started

from .actions import exposed, fold
from .const import DOMAIN, MA_DOMAIN, PLAYER_CHECK_DELAY
from .models import ThalovantConfigEntry
from .text import escape_markdown

NO_AREA_PREFIX = "music_player_no_area"
CLASH_PREFIX = "music_name_clash"
#: Where the person lands to rename or place a player that has no device page.
ENTITIES_URL = "/config/entities"


def no_area_issue_id(entry_id: str, entity_id: str) -> str:
    """The repair issue raised while an exposed Music Assistant player has no area."""
    return f"{NO_AREA_PREFIX}_{entry_id}_{entity_id}"


def clash_issue_id(entry_id: str, name: str) -> str:
    """The repair issue raised while two exposed media players share a spoken name."""
    return f"{CLASH_PREFIX}_{entry_id}_{fold(name).replace(' ', '_')}"


def _names(hass: HomeAssistant, state: State) -> set[str]:
    """The names a person can say for a media player: its name, its Assist aliases."""
    names = {fold(state.name)}
    if (entry := er.async_get(hass).async_get(state.entity_id)) is not None:
        names.update(fold(alias) for alias in entry.aliases)
        names.add(fold(entry.name))
    names.discard("")
    return names


def _platform(hass: HomeAssistant, state: State) -> str | None:
    entry = er.async_get(hass).async_get(state.entity_id)
    return entry.platform if entry is not None else None


def _has_area(hass: HomeAssistant, entry: er.RegistryEntry) -> bool:
    """Whether the entity, or failing that its device, is in an area."""
    if entry.area_id:
        return True
    device = dr.async_get(hass).async_get(entry.device_id) if entry.device_id else None
    return bool(device and device.area_id)


def _device_url(hass: HomeAssistant, entity_id: str) -> str:
    """Home Assistant's page for the entity's device, or the entity list without one."""
    entry = er.async_get(hass).async_get(entity_id)
    if entry is not None and entry.device_id:
        return f"/config/devices/device/{entry.device_id}"
    return ENTITIES_URL


def name_clash(hass: HomeAssistant, player: State, name: str) -> list[State]:
    """The other exposed media players that answer to ``name``, which ``player`` also does.

    Empty when ``name`` is not one of the player's names, or no other player has it.
    """
    wanted = fold(name)
    if not wanted or wanted not in _names(hass, player):
        return []
    return [
        other
        for other in exposed(hass, ("media_player",))
        if other.entity_id != player.entity_id and wanted in _names(hass, other)
    ]


@dataclass(frozen=True)
class _Clash:
    """Two or more exposed media players sharing one spoken name."""

    name: str
    music_assistant: State
    other: State


def _clashes(hass: HomeAssistant, players: list[State]) -> dict[str, _Clash]:
    """The names that a Music Assistant player shares with another exposed media player."""
    by_name: dict[str, list[State]] = {}
    for state in players:
        for name in _names(hass, state):
            by_name.setdefault(name, []).append(state)
    found: dict[str, _Clash] = {}
    for name, states in by_name.items():
        ours = [s for s in states if _platform(hass, s) == MA_DOMAIN]
        others = [s for s in states if _platform(hass, s) != MA_DOMAIN]
        if ours and others:
            found[name] = _Clash(name, ours[0], others[0])
    return found


class PlayerChecker:
    """Keeps the repair issues about one entry's Music Assistant players up to date."""

    def __init__(self, hass: HomeAssistant, entry: ThalovantConfigEntry) -> None:
        """Remember the entry; nothing is listened to until ``async_start``."""
        self._hass = hass
        self._entry_id = entry.entry_id
        self._raised: set[str] = set()
        self._cancel_timer: CALLBACK_TYPE | None = None

    @callback
    def async_start(self) -> Callable[[], None]:
        """Check once Home Assistant has started, then after every registry change."""
        cancels = [
            async_at_started(self._hass, self._async_check_now),
            self._hass.bus.async_listen(
                er.EVENT_ENTITY_REGISTRY_UPDATED, self._async_registry_updated
            ),
            self._hass.bus.async_listen(
                dr.EVENT_DEVICE_REGISTRY_UPDATED, self._async_registry_updated
            ),
        ]

        @callback
        def stop() -> None:
            for cancel in cancels:
                cancel()
            if self._cancel_timer is not None:
                self._cancel_timer()
                self._cancel_timer = None

        return stop

    @callback
    def _async_registry_updated(self, event: Event[Any]) -> None:
        """Look again shortly: a burst of changes is looked at once."""
        if self._cancel_timer is None:
            self._cancel_timer = async_call_later(
                self._hass, PLAYER_CHECK_DELAY, self._async_check_now
            )

    @callback
    def _async_check_now(self, *_: object) -> None:
        """Raise the issues that apply and clear the ones that no longer do."""
        self._cancel_timer = None
        hass = self._hass
        wanted: set[str] = set()
        players = exposed(hass, ("media_player",))
        entities = er.async_get(hass)
        for state in players:
            entry = entities.async_get(state.entity_id)
            if entry is None or entry.platform != MA_DOMAIN or _has_area(hass, entry):
                continue
            issue_id = no_area_issue_id(self._entry_id, state.entity_id)
            wanted.add(issue_id)
            self._raise(
                issue_id,
                "music_player_no_area",
                {
                    "player": str(state.name),
                    "device_url": _device_url(hass, state.entity_id),
                },
            )
        for clash in _clashes(hass, players).values():
            issue_id = clash_issue_id(self._entry_id, clash.name)
            wanted.add(issue_id)
            self._raise(
                issue_id,
                "music_name_clash",
                {
                    "name": str(clash.music_assistant.name),
                    "other_url": _device_url(hass, clash.other.entity_id),
                },
            )
        for issue_id in self._raised - wanted:
            ir.async_delete_issue(hass, DOMAIN, issue_id)
        self._raised = wanted

    def _raise(
        self, issue_id: str, translation_key: str, placeholders: dict[str, str]
    ) -> None:
        ir.async_create_issue(
            self._hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=translation_key,
            translation_placeholders={
                key: escape_markdown(value) for key, value in placeholders.items()
            },
        )

    @callback
    def async_clear(self) -> None:
        """Remove every issue this checker raised."""
        for issue_id in self._raised:
            ir.async_delete_issue(self._hass, DOMAIN, issue_id)
        self._raised = set()


@callback
def async_delete_entry_issues(hass: HomeAssistant, entry_id: str) -> None:
    """Remove every player issue of an entry, including ones raised before a restart."""
    registry = ir.async_get(hass)
    for domain, issue_id in list(registry.issues):
        if domain == DOMAIN and issue_id.startswith(
            (f"{NO_AREA_PREFIX}_{entry_id}_", f"{CLASH_PREFIX}_{entry_id}_")
        ):
            ir.async_delete_issue(hass, DOMAIN, issue_id)
