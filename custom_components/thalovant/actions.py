"""Carry out a structured home request against Home Assistant's own registries.

The hub's skill can send, next to the words, an ``action``: a capability (what
is wanted: power, brightness, position...), a target (name, area, floor,
domain, or the speaker's own room) and a value, absolute or relative. This
module resolves the target among the entities exposed to Assist (names and
aliases, areas, floors, domains) and calls the entity's own services, the way a
smart-home skill does, instead of leaving a sentence to Assist's parser.

It never guesses. An action it cannot resolve to exactly what was asked (no
exposed entity, two entities with the name, a domain without that capability, a
service that failed) returns ``None`` and the request goes on as the words it
carries, through Assist. Sensitive actions (locks, alarm panels, garage doors,
gates and valves opening, sirens) are only carried out when the household turned
that on in the integration's options, and an alarm is disarmed only with the
code kept in those options; otherwise they too go on as words, so Home
Assistant's own exposure rules decide. Entities are always limited to those
exposed to Assist.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import re
from typing import Any
import unicodedata

from homeassistant.components.homeassistant.exposed_entities import async_should_expose
from homeassistant.core import Context, HomeAssistant, State
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    floor_registry as fr,
)
from homeassistant.util import color as color_util

from .const import LOGGER

#: Entities one action may change at once ("all the lights upstairs").
MAX_TARGETS = 50
#: A relative brightness, position or volume step when the hub gave none, in percent.
DEFAULT_STEP = 20

#: Which domains can carry out each capability.
CAPABILITY_DOMAINS: dict[str, tuple[str, ...]] = {
    "power_on": ("light", "switch", "fan", "input_boolean", "humidifier", "media_player", "remote", "climate", "water_heater", "automation", "cover", "valve", "siren"),
    "power_off": ("light", "switch", "fan", "input_boolean", "humidifier", "media_player", "remote", "climate", "water_heater", "automation", "cover", "valve", "siren"),
    "toggle": ("light", "switch", "fan", "input_boolean", "cover"),
    "brightness": ("light",),
    "color": ("light",),
    "color_temperature": ("light",),
    "position": ("cover", "valve"),
    "fan_speed": ("fan",),
    "temperature": ("climate", "water_heater"),
    "hvac_mode": ("climate",),
    "humidity": ("humidifier",),
    "lock": ("lock",),
    "unlock": ("lock",),
    "volume": ("media_player",),
    "mute": ("media_player",),
    "unmute": ("media_player",),
    "playback": ("media_player",),
    "activate": ("scene", "script", "automation", "button", "input_button"),
    "start": ("vacuum", "lawn_mower"),
    "stop": ("vacuum",),
    "dock": ("vacuum", "lawn_mower"),
    "arm": ("alarm_control_panel",),
    "disarm": ("alarm_control_panel",),
    "state": (),
}
#: The domains a bare area or floor means when the action names none: what a person
#: means by "turn off the kitchen" is the lights.
DEFAULT_DOMAINS = ("light",)
COLOUR_TEMPERATURES = {"candle light": 1900, "candlelight": 1900, "warm white": 2700, "warm": 2700,
                       "soft white": 2700, "neutral white": 3500, "cool white": 4000, "cold white": 4000,
                       "cool": 4000, "daylight": 6500, "day light": 6500}
PLAYBACK = {"play": "media_play", "pause": "media_pause", "stop": "media_stop",
            "next": "media_next_track", "previous": "media_previous_track"}
ARM_MODES = {"away": "alarm_arm_away", "home": "alarm_arm_home", "night": "alarm_arm_night"}
SENSITIVE_COVER_CLASSES = frozenset({"garage", "gate", "door"})
STATE_DOMAINS_NAMES = ()


@dataclass
class ActionResult:
    """What was done: a translation key for the spoken answer and its placeholders."""

    response_type: str  # "action_done" or "query_answer"
    speech_key: str
    placeholders: dict[str, str] = field(default_factory=dict)
    changed: list[str] = field(default_factory=list)


def fold(text: Any) -> str:
    """A name as it is compared: no accents, no punctuation, lower case, single spaces."""
    if not isinstance(text, str):
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w\s]", " ", text.casefold()).split())


class _Registries:
    """The registries one resolution reads."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.entities = er.async_get(hass)
        self.devices = dr.async_get(hass)
        self.areas = ar.async_get(hass)
        self.floors = fr.async_get(hass)

    def names(self, state: State) -> set[str]:
        out = {fold(state.name)}
        if (entry := self.entities.async_get(state.entity_id)) is not None:
            out.update(fold(a) for a in entry.aliases)
            out.add(fold(entry.name))
        out.discard("")
        return out

    def area_id(self, entity_id: str) -> str | None:
        entry = self.entities.async_get(entity_id)
        if entry is None:
            return None
        if entry.area_id:
            return entry.area_id
        if entry.device_id and (device := self.devices.async_get(entry.device_id)):
            return device.area_id
        return None

    def area_matches(self, area_id: str | None, wanted: str) -> bool:
        if area_id is None or (area := self.areas.async_get_area(area_id)) is None:
            return False
        return wanted in {fold(area.name), *(fold(a) for a in area.aliases)}

    def floor_matches(self, area_id: str | None, wanted: str) -> bool:
        if area_id is None or (area := self.areas.async_get_area(area_id)) is None or not area.floor_id:
            return False
        floor = self.floors.async_get_floor(area.floor_id)
        return floor is not None and wanted in {fold(floor.name), *(fold(a) for a in floor.aliases)}

    def device_area(self, device_id: str | None) -> str | None:
        if not device_id or (device := self.devices.async_get(device_id)) is None:
            return None
        return device.area_id


def resolve(
    hass: HomeAssistant, action: Mapping[str, Any], device_id: str | None
) -> list[State] | None:
    """The exposed entities the action means, or None when it is not exactly resolved."""
    capability = action.get("capability")
    target = action.get("target") or {}
    domains = CAPABILITY_DOMAINS.get(capability)
    if domains is None:
        return None
    if target.get("domain"):
        domains = tuple(d for d in domains if d == target["domain"]) if domains else (target["domain"],)
        if not domains:
            return None
    reg = _Registries(hass)
    name, area, floor = (fold(target.get(k)) for k in ("name", "area", "floor"))
    here = target.get("here") is True
    area_id_here = reg.device_area(device_id) if here else None
    if here and area_id_here is None:
        return None  # the speaker has no room: Assist asks which

    pool: list[State] = []
    for state in hass.states.async_all():
        domain = state.entity_id.split(".", 1)[0]
        if domains and domain not in domains:
            continue
        if not async_should_expose(hass, "conversation", state.entity_id):
            continue
        pool.append(state)

    def keep(state: State) -> bool:
        entity_area = reg.area_id(state.entity_id)
        if here and entity_area != area_id_here:
            return False
        if area and not reg.area_matches(entity_area, area):
            return False
        if floor and not reg.floor_matches(entity_area, floor):
            return False
        return True

    scoped = [s for s in pool if keep(s)]
    if name:
        exact = [s for s in scoped if name in reg.names(s)]
        if len(exact) > 1:
            return None  # which one? Assist asks
        found = exact
    else:
        if not (area or floor or here or target.get("all")):
            return None
        if not domains:
            return None
        if not target.get("domain") and capability in ("power_on", "power_off", "toggle"):
            scoped = [s for s in scoped if s.entity_id.split(".", 1)[0] in DEFAULT_DOMAINS]
        found = scoped
    if not found or len(found) > MAX_TARGETS:
        return None
    return found


def _is_sensitive(capability: str, state: State) -> bool:
    domain = state.entity_id.split(".", 1)[0]
    if capability in ("lock", "unlock", "arm", "disarm"):
        return True
    if domain == "siren" and capability == "power_on":
        return True
    if domain == "valve" and capability in ("power_on", "position"):
        return True
    if domain == "cover" and state.attributes.get("device_class") in SENSITIVE_COVER_CLASSES:
        return capability in ("power_on", "position", "toggle")
    return False


def _pct(value: Any, default: float = 0.0) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else default


def _calls(
    action: Mapping[str, Any], state: State, alarm_code: str | None
) -> tuple[str, str, dict[str, Any]] | None:
    """The one service call that does the action on one entity, or None."""
    capability = action["capability"]
    value = action.get("value")
    relative = action.get("mode") == "relative"
    domain = state.entity_id.split(".", 1)[0]
    attrs = state.attributes
    eid = state.entity_id
    if capability in ("power_on", "power_off"):
        on = capability == "power_on"
        if domain == "cover":
            return domain, "open_cover" if on else "close_cover", {}
        if domain == "valve":
            return domain, "open_valve" if on else "close_valve", {}
        if domain == "automation":
            return domain, "turn_on" if on else "turn_off", {}
        return domain, "turn_on" if on else "turn_off", {}
    if capability == "toggle":
        return domain, "toggle", {}
    if capability == "brightness" and domain == "light":
        if relative:
            current = _pct(attrs.get("brightness")) * 100 / 255 if state.state == "on" else 0.0
            level = current + (_pct(value, DEFAULT_STEP))
        else:
            level = _pct(value, -1)
        if level < 0 and not relative:
            return None
        level = max(1, min(100, round(level)))
        return "light", "turn_on", {"brightness_pct": level}
    if capability == "color" and domain == "light" and isinstance(value, str):
        try:
            rgb = color_util.color_name_to_rgb(value.replace(" ", ""))
        except ValueError:
            return None
        return "light", "turn_on", {"rgb_color": list(rgb)}
    if capability == "color_temperature" and domain == "light":
        kelvin = value if isinstance(value, (int, float)) and not isinstance(value, bool) else COLOUR_TEMPERATURES.get(fold(value))
        if not kelvin:
            return None
        return "light", "turn_on", {"color_temp_kelvin": int(kelvin)}
    if capability == "position" and domain in ("cover", "valve") and value is not None:
        key = "current_position"
        if relative:
            position = _pct(attrs.get(key)) + _pct(value)
        else:
            position = _pct(value, -1)
            if position < 0:
                return None
        position = max(0, min(100, round(position)))
        return domain, f"set_{domain}_position", {"position": position}
    if capability == "fan_speed" and domain == "fan" and value is not None:
        if relative:
            step = _pct(attrs.get("percentage_step"), 25)
            direction = 1 if _pct(value) >= 0 else -1
            level = _pct(attrs.get("percentage")) + direction * max(step, abs(_pct(value)))
        else:
            level = _pct(value, -1)
            if level < 0:
                return None
        return "fan", "set_percentage", {"percentage": max(0, min(100, round(level)))}
    if capability == "temperature" and domain in ("climate", "water_heater") and value is not None:
        if relative:
            base = attrs.get("temperature")
            if not isinstance(base, (int, float)):
                base = attrs.get("current_temperature")
            if not isinstance(base, (int, float)):
                return None
            temp = base + _pct(value)
        else:
            temp = _pct(value, float("nan"))
            if temp != temp:
                return None
        return domain, "set_temperature", {"temperature": round(temp * 2) / 2}
    if capability == "hvac_mode" and domain == "climate" and isinstance(value, str):
        return "climate", "set_hvac_mode", {"hvac_mode": fold(value).replace(" ", "_")}
    if capability == "humidity" and domain == "humidifier" and value is not None:
        return "humidifier", "set_humidity", {"humidity": max(0, min(100, round(_pct(value))))}
    if capability in ("lock", "unlock") and domain == "lock":
        return "lock", capability, {}
    if capability == "volume" and domain == "media_player" and value is not None:
        if relative:
            level = _pct(attrs.get("volume_level")) + _pct(value) / 100
        else:
            level = _pct(value, -1) / 100
            if level < 0:
                return None
        return "media_player", "volume_set", {"volume_level": max(0.0, min(1.0, round(level, 2)))}
    if capability in ("mute", "unmute") and domain == "media_player":
        return "media_player", "volume_mute", {"is_volume_muted": capability == "mute"}
    if capability == "playback" and domain == "media_player" and value in PLAYBACK:
        return "media_player", PLAYBACK[value], {}
    if capability == "activate":
        service = {"scene": "turn_on", "script": "turn_on", "automation": "trigger",
                   "button": "press", "input_button": "press"}.get(domain)
        return (domain, service, {}) if service else None
    if capability in ("start", "stop", "dock"):
        service = {("vacuum", "start"): "start", ("vacuum", "stop"): "stop", ("vacuum", "dock"): "return_to_base",
                   ("lawn_mower", "start"): "start_mowing", ("lawn_mower", "dock"): "dock"}.get((domain, capability))
        return (domain, service, {}) if service else None
    if capability == "arm" and domain == "alarm_control_panel":
        mode = ARM_MODES.get(fold(value) if value else "away")
        if mode is None:
            return None
        data: dict[str, Any] = {"code": alarm_code} if alarm_code else {}
        return "alarm_control_panel", mode, data
    if capability == "disarm" and domain == "alarm_control_panel":
        if not alarm_code:
            return None
        return "alarm_control_panel", "alarm_disarm", {"code": alarm_code}
    return None


async def async_execute(
    hass: HomeAssistant,
    action: Mapping[str, Any],
    *,
    device_id: str | None,
    allow_sensitive: bool = False,
    alarm_code: str | None = None,
    context: Context | None = None,
) -> ActionResult | None:
    """Carry the action out, or return None so the words go on to Assist."""
    capability = action.get("capability")
    if capability not in CAPABILITY_DOMAINS:
        return None
    states = resolve(hass, action, device_id) if capability != "state" else _state_targets(hass, action, device_id)
    if not states:
        return None
    if capability == "state":
        return _answer_state(hass, states)
    if not allow_sensitive and any(_is_sensitive(capability, s) for s in states):
        LOGGER.debug("Structured %s on %s left to Assist: sensitive actions are off", capability, states[0].entity_id)
        return None
    calls = []
    for state in states:
        call = _calls(action, state, alarm_code)
        if call is None or not hass.services.has_service(call[0], call[1]):
            return None  # one entity it cannot do: do none of it, let Assist answer
        calls.append((state, call))
    ctx = context or Context()
    for state, (domain, service, data) in calls:
        try:
            await hass.services.async_call(domain, service, {"entity_id": state.entity_id, **data}, blocking=True, context=ctx)
        except Exception as err:  # noqa: BLE001 - any failure goes on as words
            LOGGER.debug("Structured %s on %s failed: %s", service, state.entity_id, type(err).__name__)
            return None
    names = [s.name for s in states]
    return ActionResult("action_done", "action_done", {"name": names[0] if len(names) == 1 else str(len(names))},
                        [s.entity_id for s in states])


def _state_targets(hass: HomeAssistant, action: Mapping[str, Any], device_id: str | None) -> list[State] | None:
    """A state read names an entity (any domain it is exposed in)."""
    target = dict(action.get("target") or {})
    probe = {"capability": "state", "target": target}
    reg_domains = target.get("domain")
    # resolve() has no domains for "state": widen to the named domain or every exposed entity
    original = CAPABILITY_DOMAINS["state"]
    try:
        if reg_domains:
            CAPABILITY_DOMAINS["state"] = (reg_domains,)
        else:
            CAPABILITY_DOMAINS["state"] = tuple(sorted({s.entity_id.split(".", 1)[0] for s in hass.states.async_all()}))
        return resolve(hass, probe, device_id)
    finally:
        CAPABILITY_DOMAINS["state"] = original


def _answer_state(hass: HomeAssistant, states: list[State]) -> ActionResult:
    first = states[0]
    unit = first.attributes.get("unit_of_measurement")
    value = f"{first.state} {unit}".strip() if unit else first.state
    return ActionResult("query_answer", "action_state", {"name": first.name, "state": value})


Resolver = Callable[..., Any]
