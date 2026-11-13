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
import math
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
    "power_on": (
        "light",
        "switch",
        "fan",
        "input_boolean",
        "humidifier",
        "media_player",
        "remote",
        "climate",
        "water_heater",
        "automation",
        "cover",
        "valve",
        "siren",
    ),
    "power_off": (
        "light",
        "switch",
        "fan",
        "input_boolean",
        "humidifier",
        "media_player",
        "remote",
        "climate",
        "water_heater",
        "automation",
        "cover",
        "valve",
        "siren",
    ),
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
COLOUR_TEMPERATURES = {
    "candle light": 1900,
    "candlelight": 1900,
    "warm white": 2700,
    "warm": 2700,
    "soft white": 2700,
    "neutral white": 3500,
    "cool white": 4000,
    "cold white": 4000,
    "cool": 4000,
    "daylight": 6500,
    "day light": 6500,
}
PLAYBACK = {
    "play": "media_play",
    "pause": "media_pause",
    "stop": "media_stop",
    "next": "media_next_track",
    "previous": "media_previous_track",
}
ARM_MODES = {
    "away": "alarm_arm_away",
    "home": "alarm_arm_home",
    "night": "alarm_arm_night",
}
SENSITIVE_COVER_CLASSES = frozenset({"garage", "gate", "door"})


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

    def area_ids(self, wanted: str) -> set[str]:
        """The areas whose name or alias is ``wanted`` (more than one means it is ambiguous)."""
        return {
            a.id
            for a in self.areas.async_list_areas()
            if wanted in {fold(a.name), *(fold(x) for x in a.aliases)}
        }

    def floor_ids(self, wanted: str) -> set[str]:
        """The floors whose name or alias is ``wanted``."""
        return {
            f.floor_id
            for f in self.floors.async_list_floors()
            if wanted in {fold(f.name), *(fold(x) for x in f.aliases)}
        }

    def floor_of(self, area_id: str | None) -> str | None:
        if area_id is None or (area := self.areas.async_get_area(area_id)) is None:
            return None
        return area.floor_id

    def device_area(self, device_id: str | None) -> str | None:
        if not device_id or (device := self.devices.async_get(device_id)) is None:
            return None
        return device.area_id


def resolve(
    hass: HomeAssistant,
    action: Mapping[str, Any],
    device_id: str | None,
    any_domain: bool = False,
) -> list[State] | None:
    """The exposed entities the action means, or None when it is not exactly resolved.

    ``any_domain`` is for a state read, which may name an entity of any domain.
    """
    capability = action.get("capability")
    target = action.get("target") or {}
    if not isinstance(capability, str):
        return None
    domains = CAPABILITY_DOMAINS.get(capability)
    if domains is None:
        return None
    if any_domain:
        domains = (target["domain"],) if target.get("domain") else ()
    elif target.get("domain"):
        domains = (
            tuple(d for d in domains if d == target["domain"])
            if domains
            else (target["domain"],)
        )
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

    # A name two rooms share ("guest") is not a room: ask, do not change both.
    area_set = reg.area_ids(area) if area else None
    floor_set = reg.floor_ids(floor) if floor else None
    if (area_set is not None and len(area_set) != 1) or (
        floor_set is not None and len(floor_set) != 1
    ):
        return None

    def keep(state: State) -> bool:
        entity_area = reg.area_id(state.entity_id)
        if here and entity_area != area_id_here:
            return False
        if area_set is not None and entity_area not in area_set:
            return False
        if floor_set is not None and reg.floor_of(entity_area) not in floor_set:
            return False
        return True

    scoped = [s for s in pool if keep(s)]
    if name:
        exact = [s for s in scoped if name in reg.names(s)]
        if len(exact) > 1:
            return None  # which one? Assist asks
        found = exact
        if not found and not (area or floor or here):
            # "make the living room warmer": the hub cannot tell a room from a device, so a name
            # that is no entity's is read as an area, then as a floor
            if len(areas_named := reg.area_ids(name)) == 1:
                found = [s for s in scoped if reg.area_id(s.entity_id) in areas_named]
            elif not areas_named and len(floors_named := reg.floor_ids(name)) == 1:
                found = [
                    s
                    for s in scoped
                    if reg.floor_of(reg.area_id(s.entity_id)) in floors_named
                ]
    else:
        if not (area or floor or here or target.get("all")):
            return None
        if not target.get("domain") and capability in (
            "power_on",
            "power_off",
            "toggle",
        ):
            scoped = [
                s for s in scoped if s.entity_id.split(".", 1)[0] in DEFAULT_DOMAINS
            ]
        found = scoped
    if not found or len(found) > MAX_TARGETS:
        return None
    return found


def _is_sensitive(capability: str, state: State) -> bool:
    domain = state.entity_id.split(".", 1)[0]
    if capability in ("lock", "unlock", "arm", "disarm"):
        return True
    if domain == "siren":
        return capability in ("power_on", "power_off", "toggle")
    if domain == "valve" and capability in ("power_on", "position"):
        return True
    if (
        domain == "cover"
        and state.attributes.get("device_class") in SENSITIVE_COVER_CLASSES
    ):
        return capability in ("power_on", "position", "toggle")
    return False


def _num(value: Any) -> float | None:
    """A number, or None: a string or a boolean is never read as one."""
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or math.isnan(value)
    ):
        return None
    return float(value)


def _pct(value: Any, default: float = 0.0) -> float:
    number = _num(value)
    return default if number is None else number


type Call = tuple[str, str, dict[str, Any]]


class _Request:
    """One entity and what is asked of it, for the builders below."""

    def __init__(self, action: Mapping[str, Any], state: State, alarm_code: str | None):
        self.capability: str = action["capability"]
        self.value = action.get("value")
        self.relative = action.get("mode") == "relative"
        self.state = state
        self.domain = state.entity_id.split(".", 1)[0]
        self.attrs = state.attributes
        self.alarm_code = alarm_code


def _power(r: _Request) -> Call | None:
    on = r.capability == "power_on"
    if r.domain == "cover":
        return r.domain, "open_cover" if on else "close_cover", {}
    if r.domain == "valve":
        return r.domain, "open_valve" if on else "close_valve", {}
    return r.domain, "turn_on" if on else "turn_off", {}


def _toggle(r: _Request) -> Call | None:
    return r.domain, "toggle", {}


def _brightness(r: _Request) -> Call | None:
    step = _num(r.value)
    if r.domain != "light" or step is None:
        return None
    if r.relative:
        current = (
            _pct(r.attrs.get("brightness")) * 100 / 255
            if r.state.state == "on"
            else 0.0
        )
        level = current + step
    else:
        if step < 0:
            return None
        level = step
        if level <= 0:
            return "light", "turn_off", {}  # zero brightness is off
    return "light", "turn_on", {"brightness_pct": max(1, min(100, round(level)))}


def _color(r: _Request) -> Call | None:
    if r.domain != "light" or not isinstance(r.value, str):
        return None
    try:
        rgb = color_util.color_name_to_rgb(r.value.replace(" ", ""))
    except ValueError:
        return None
    return "light", "turn_on", {"rgb_color": list(rgb)}


def _color_temperature(r: _Request) -> Call | None:
    if r.domain != "light":
        return None
    kelvin = _num(r.value) or COLOUR_TEMPERATURES.get(fold(r.value))
    return ("light", "turn_on", {"color_temp_kelvin": int(kelvin)}) if kelvin else None


def _position(r: _Request) -> Call | None:
    number = _num(r.value)
    if r.domain not in ("cover", "valve") or number is None:
        return None
    if r.relative:
        current = _num(r.attrs.get("current_position"))
        if current is None:
            return None  # an unknown position cannot be moved relatively
        position = current + number
    else:
        if number < 0:
            return None
        position = number
    return (
        r.domain,
        f"set_{r.domain}_position",
        {"position": max(0, min(100, round(position)))},
    )


def _fan_speed(r: _Request) -> Call | None:
    number = _num(r.value)
    if r.domain != "fan" or number is None:
        return None
    if r.relative:
        step = _pct(r.attrs.get("percentage_step"), 25)
        direction = 1 if number >= 0 else -1
        current = _pct(r.attrs.get("percentage"))
        level = current + direction * max(step, abs(number))
        if direction < 0 and current > 0:
            level = max(level, step)  # "slower" never switches the fan off
    else:
        if number < 0:
            return None
        level = number
    return "fan", "set_percentage", {"percentage": max(0, min(100, round(level)))}


def _temperature(r: _Request) -> Call | None:
    number = _num(r.value)
    if r.domain not in ("climate", "water_heater") or number is None:
        return None
    if r.relative:
        base = _num(r.attrs.get("temperature"))
        if base is None:
            base = _num(r.attrs.get("current_temperature"))
        if base is None:
            return None
        temp = base + number
    else:
        temp = number
    return r.domain, "set_temperature", {"temperature": round(temp * 2) / 2}


def _hvac_mode(r: _Request) -> Call | None:
    if r.domain != "climate" or not isinstance(r.value, str):
        return None
    return "climate", "set_hvac_mode", {"hvac_mode": fold(r.value).replace(" ", "_")}


def _humidity(r: _Request) -> Call | None:
    number = _num(r.value)
    if r.domain != "humidifier" or number is None:
        return None
    return "humidifier", "set_humidity", {"humidity": max(0, min(100, round(number)))}


def _lock(r: _Request) -> Call | None:
    return ("lock", r.capability, {}) if r.domain == "lock" else None


def _volume(r: _Request) -> Call | None:
    number = _num(r.value)
    if r.domain != "media_player" or number is None:
        return None
    if r.relative:
        level = _pct(r.attrs.get("volume_level")) + number / 100
    else:
        if number < 0:
            return None
        level = number / 100
    return (
        "media_player",
        "volume_set",
        {"volume_level": max(0.0, min(1.0, round(level, 2)))},
    )


def _mute(r: _Request) -> Call | None:
    if r.domain != "media_player":
        return None
    return "media_player", "volume_mute", {"is_volume_muted": r.capability == "mute"}


def _playback(r: _Request) -> Call | None:
    if r.domain != "media_player" or r.value not in PLAYBACK:
        return None
    return "media_player", PLAYBACK[r.value], {}


def _activate(r: _Request) -> Call | None:
    service = {
        "scene": "turn_on",
        "script": "turn_on",
        "automation": "trigger",
        "button": "press",
        "input_button": "press",
    }.get(r.domain)
    return (r.domain, service, {}) if service else None


def _run(r: _Request) -> Call | None:
    service = {
        ("vacuum", "start"): "start",
        ("vacuum", "stop"): "stop",
        ("vacuum", "dock"): "return_to_base",
        ("lawn_mower", "start"): "start_mowing",
        ("lawn_mower", "dock"): "dock",
    }.get((r.domain, r.capability))
    return (r.domain, service, {}) if service else None


def _arm(r: _Request) -> Call | None:
    if r.domain != "alarm_control_panel":
        return None
    mode = ARM_MODES.get(fold(r.value) if r.value else "away")
    if mode is None:
        return None
    return "alarm_control_panel", mode, {"code": r.alarm_code} if r.alarm_code else {}


def _disarm(r: _Request) -> Call | None:
    if r.domain != "alarm_control_panel" or not r.alarm_code:
        return None
    return "alarm_control_panel", "alarm_disarm", {"code": r.alarm_code}


BUILDERS: dict[str, Callable[[_Request], Call | None]] = {
    "power_on": _power,
    "power_off": _power,
    "toggle": _toggle,
    "brightness": _brightness,
    "color": _color,
    "color_temperature": _color_temperature,
    "position": _position,
    "fan_speed": _fan_speed,
    "temperature": _temperature,
    "hvac_mode": _hvac_mode,
    "humidity": _humidity,
    "lock": _lock,
    "unlock": _lock,
    "volume": _volume,
    "mute": _mute,
    "unmute": _mute,
    "playback": _playback,
    "activate": _activate,
    "start": _run,
    "stop": _run,
    "dock": _run,
    "arm": _arm,
    "disarm": _disarm,
}


def _calls(
    action: Mapping[str, Any], state: State, alarm_code: str | None
) -> Call | None:
    """The one service call that does the action on one entity, or None."""
    builder = BUILDERS.get(action["capability"])
    return builder(_Request(action, state, alarm_code)) if builder else None


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
    states = resolve(hass, action, device_id, any_domain=capability == "state")
    if not states:
        return None
    if capability == "state":
        # one entity: an area's worth of states would answer with the first and drop the rest
        return _answer_state(hass, states) if len(states) == 1 else None
    if not allow_sensitive and any(_is_sensitive(capability, s) for s in states):
        LOGGER.debug(
            "Structured %s on %s left to Assist: sensitive actions are off",
            capability,
            states[0].entity_id,
        )
        return None
    calls = []
    for state in states:
        call = _calls(action, state, alarm_code)
        if call is None or not hass.services.has_service(call[0], call[1]):
            return None  # one entity it cannot do: do none of it, let Assist answer
        calls.append((state, call))
    ctx = context or Context()
    done: list[str] = []
    for state, (domain, service, data) in calls:
        try:
            await hass.services.async_call(
                domain,
                service,
                {"entity_id": state.entity_id, **data},
                blocking=True,
                context=ctx,
            )
        except Exception as err:  # noqa: BLE001 - see below
            LOGGER.debug(
                "Structured %s on %s failed: %s",
                service,
                state.entity_id,
                type(err).__name__,
            )
            if not done:
                return None  # nothing changed: the words may still work
            # Part of it is done. Sending the sentence to Assist now would run the intent again on
            # everything, doubling a relative step and undoing a toggle: say it was partial.
            return ActionResult("error", "action_partial", {"name": state.name}, done)
        done.append(state.entity_id)
    names = [s.name for s in states]
    return ActionResult(
        "action_done",
        "action_done",
        {"name": names[0] if len(names) == 1 else str(len(names))},
        [s.entity_id for s in states],
    )


def _answer_state(hass: HomeAssistant, states: list[State]) -> ActionResult:
    first = states[0]
    unit = first.attributes.get("unit_of_measurement")
    value = f"{first.state} {unit}".strip() if unit else first.state
    return ActionResult(
        "query_answer", "action_state", {"name": first.name, "state": value}
    )
