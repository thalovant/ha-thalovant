"""Every capability builder and registry edge of the structured actions, case by case."""

from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.thalovant.actions import (
    BUILDERS,
    _calls,
    _is_sensitive,
    _num,
    resolve,
)
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.setup import async_setup_component

from .test_actions import _home, action


def _state(eid: str, state: str = "on", **attrs: Any) -> State:
    return State(eid, state, attrs)


def _do(
    capability: str,
    state: State,
    value: Any = None,
    mode: str | None = None,
    code: str | None = None,
):
    act: dict[str, Any] = {"v": 1, "capability": capability, "target": {"name": "x"}}
    if value is not None:
        act["value"] = value
    if mode:
        act["mode"] = mode
    return _calls(act, state, code)


CASES: list[tuple[str, State, Any, str | None, str | None, Any]] = [
    # capability, state, value, mode, alarm code, expected call (None: cannot be done)
    ("power_on", _state("valve.v"), None, None, None, ("valve", "open_valve", {})),
    ("power_off", _state("valve.v"), None, None, None, ("valve", "close_valve", {})),
    ("power_off", _state("cover.c"), None, None, None, ("cover", "close_cover", {})),
    ("brightness", _state("switch.s"), 30, None, None, None),
    ("brightness", _state("light.l"), "x", None, None, None),
    ("brightness", _state("light.l"), -5, "absolute", None, None),
    (
        "brightness",
        _state("light.l", "off"),
        20,
        "relative",
        None,
        ("light", "turn_on", {"brightness_pct": 20}),
    ),
    (
        "brightness",
        _state("light.l", brightness=255),
        -150,
        "relative",
        None,
        ("light", "turn_on", {"brightness_pct": 1}),
    ),
    ("color", _state("switch.s"), "red", None, None, None),
    ("color", _state("light.l"), "notacolour", None, None, None),
    ("color_temperature", _state("switch.s"), 2700, None, None, None),
    ("color_temperature", _state("light.l"), "no such white", None, None, None),
    (
        "color_temperature",
        _state("light.l"),
        3000,
        None,
        None,
        ("light", "turn_on", {"color_temp_kelvin": 3000}),
    ),
    ("position", _state("light.l"), 50, None, None, None),
    ("position", _state("cover.c"), "half", None, None, None),
    (
        "position",
        _state("cover.c", current_position=40),
        20,
        "relative",
        None,
        ("cover", "set_cover_position", {"position": 60}),
    ),
    ("position", _state("cover.c"), -5, None, None, None),
    (
        "position",
        _state("valve.v"),
        30,
        None,
        None,
        ("valve", "set_valve_position", {"position": 30}),
    ),
    ("fan_speed", _state("light.l"), 50, None, None, None),
    ("fan_speed", _state("fan.f"), -3, None, None, None),
    (
        "fan_speed",
        _state("fan.f"),
        60,
        None,
        None,
        ("fan", "set_percentage", {"percentage": 60}),
    ),
    (
        "fan_speed",
        _state("fan.f", percentage=50, percentage_step=25),
        -1,
        "relative",
        None,
        ("fan", "set_percentage", {"percentage": 25}),
    ),
    ("fan_speed", _state("fan.f"), 1, "relative", None, None),
    ("volume", _state("media_player.m", "off"), 10, "relative", None, None),
    (
        "volume",
        _state("media_player.m", volume_level=0.4),
        10,
        "relative",
        None,
        ("media_player", "volume_set", {"volume_level": 0.5}),
    ),
    ("temperature", _state("light.l"), 20, None, None, None),
    ("temperature", _state("climate.c"), "hot", None, None, None),
    (
        "temperature",
        _state("climate.c", current_temperature=19),
        1,
        "relative",
        None,
        ("climate", "set_temperature", {"temperature": 20.0}),
    ),
    ("temperature", _state("climate.c"), 1, "relative", None, None),
    (
        "temperature",
        _state("climate.c"),
        21.4,
        "absolute",
        None,
        ("climate", "set_temperature", {"temperature": 21.5}),
    ),
    ("hvac_mode", _state("light.l"), "heat", None, None, None),
    (
        "hvac_mode",
        _state("climate.c"),
        "Heat Cool",
        None,
        None,
        ("climate", "set_hvac_mode", {"hvac_mode": "heat_cool"}),
    ),
    ("humidity", _state("light.l"), 50, None, None, None),
    ("lock", _state("light.l"), None, None, None, None),
    ("lock", _state("lock.l"), None, None, None, ("lock", "lock", {})),
    ("volume", _state("light.l"), 10, None, None, None),
    ("volume", _state("media_player.m"), -5, "absolute", None, None),
    (
        "volume",
        _state("media_player.m"),
        30,
        "absolute",
        None,
        ("media_player", "volume_set", {"volume_level": 0.3}),
    ),
    ("mute", _state("light.l"), None, None, None, None),
    (
        "unmute",
        _state("media_player.m"),
        None,
        None,
        None,
        ("media_player", "volume_mute", {"is_volume_muted": False}),
    ),
    ("playback", _state("media_player.m"), "rewind", None, None, None),
    (
        "playback",
        _state("media_player.m"),
        "pause",
        None,
        None,
        ("media_player", "media_pause", {}),
    ),
    ("activate", _state("light.l"), None, None, None, None),
    ("activate", _state("button.b"), None, None, None, ("button", "press", {})),
    ("start", _state("light.l"), None, None, None, None),
    ("dock", _state("lawn_mower.m"), None, None, None, ("lawn_mower", "dock", {})),
    ("arm", _state("light.l"), None, None, None, None),
    ("arm", _state("alarm_control_panel.a"), "sideways", None, None, None),
    (
        "arm",
        _state("alarm_control_panel.a"),
        "night",
        None,
        "1234",
        ("alarm_control_panel", "alarm_arm_night", {"code": "1234"}),
    ),
    (
        "arm",
        _state("alarm_control_panel.a"),
        None,
        None,
        None,
        ("alarm_control_panel", "alarm_arm_away", {}),
    ),
    ("disarm", _state("light.l"), None, None, "1234", None),
]


@pytest.mark.parametrize(
    ("capability", "state", "value", "mode", "code", "expected"), CASES
)
def test_each_builder_does_exactly_what_it_can(
    capability, state, value, mode, code, expected
) -> None:
    assert _do(capability, state, value, mode, code) == expected


def test_a_capability_without_a_builder_is_nothing() -> None:
    assert _calls({"capability": "teleport"}, _state("light.l"), None) is None
    assert set(BUILDERS) >= {"power_on", "disarm", "dock"}


@pytest.mark.parametrize("value", [True, "5", None, float("nan")])
def test_only_real_numbers_are_numbers(value) -> None:
    assert _num(value) is None


@pytest.mark.parametrize(
    ("capability", "state", "sensitive"),
    [
        ("lock", _state("lock.l"), True),
        ("power_on", _state("valve.v"), True),
        ("position", _state("valve.v"), True),
        ("power_off", _state("valve.v"), False),
        ("toggle", _state("siren.s"), True),
        ("power_on", _state("cover.g", device_class="garage"), True),
        ("power_off", _state("cover.g", device_class="garage"), False),
        ("power_on", _state("cover.b", device_class="blind"), False),
        ("power_on", _state("light.l"), False),
    ],
)
def test_what_is_sensitive(capability, state, sensitive) -> None:
    assert _is_sensitive(capability, state) is sensitive


async def test_registry_edges(hass: HomeAssistant) -> None:
    ids = await _home(hass)
    # an unknown capability, a missing one, a domain the capability lacks
    assert resolve(hass, {"capability": 5, "target": {"name": "desk"}}, None) is None
    assert (
        resolve(hass, {"capability": "teleport", "target": {"name": "desk"}}, None)
        is None
    )
    assert (
        resolve(hass, action("brightness", name="desk", domain="fan"), ids["speaker"])
        is None
    )
    # a state read of any domain, by name, by area, by here
    assert resolve(
        hass, action("state", name="front door"), ids["speaker"], any_domain=True
    )
    assert resolve(
        hass,
        action("state", name="power", domain="sensor"),
        ids["speaker"],
        any_domain=True,
    )
    assert resolve(
        hass,
        action("state", area="kitchen", domain="sensor"),
        ids["speaker"],
        any_domain=True,
    )
    # no name, area, floor, here or all
    assert (
        resolve(
            hass,
            {"v": 1, "capability": "power_off", "target": {"domain": "light"}},
            None,
        )
        is None
    )
    # "all" of a domain
    assert resolve(hass, action("power_off", all=True, domain="light"), None)
    # an entity whose area comes from its device; an entity without a registry entry has no area
    ents, devs, areas = er.async_get(hass), dr.async_get(hass), ar.async_get(hass)
    entry = MockConfigEntry(domain="test2")
    entry.add_to_hass(hass)
    den = areas.async_create("Den")
    device = devs.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("t", "d")}, name="Dev"
    )
    devs.async_update_device(device.id, area_id=den.id)
    reg = ents.async_get_or_create(
        "light",
        "test2",
        "dd",
        suggested_object_id="dd",
        config_entry=entry,
        device_id=device.id,
    )
    hass.states.async_set(reg.entity_id, "on", {"friendly_name": "Dd"})
    from homeassistant.components.homeassistant.exposed_entities import (
        async_expose_entity,
    )

    async_expose_entity(hass, "conversation", reg.entity_id, True)
    hass.states.async_set("light.ghost", "on", {"friendly_name": "Ghost"})
    async_expose_entity(hass, "conversation", "light.ghost", True)
    assert [
        s.entity_id
        for s in resolve(
            hass, action("power_off", area="den", domain="light"), ids["speaker"]
        )
    ] == [reg.entity_id]
    assert (
        resolve(
            hass,
            action("power_off", area="den", name="ghost", domain="light"),
            ids["speaker"],
        )
        is None
    )
    assert (
        resolve(
            hass, action("power_off", floor="nowhere", domain="light"), ids["speaker"]
        )
        is None
    )
    assert (
        resolve(hass, action("power_off", here=True, domain="light"), "no-such-device")
        is None
    )
    # more than MAX_TARGETS entities are never changed at once
    for i in range(60):
        hass.states.async_set(f"switch.many{i}", "on", {"friendly_name": f"Many {i}"})
        async_expose_entity(hass, "conversation", f"switch.many{i}", True)
    assert resolve(hass, action("power_off", all=True, domain="switch"), None) is None


async def test_the_whole_house_of_domains_is_known(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, "homeassistant", {})
    assert resolve(hass, action("state"), None, any_domain=True) is None


async def test_floor_of_an_unknown_area_is_none(hass: HomeAssistant) -> None:
    from custom_components.thalovant.actions import _Registries

    await _home(hass)
    reg = _Registries(hass)
    assert reg.floor_of(None) is None
    assert reg.floor_of("no-such-area") is None
