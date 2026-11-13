"""Structured actions: resolved against the registries, limited to what Assist may see."""

from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.thalovant.actions import async_execute, fold, resolve
from homeassistant.components.homeassistant.exposed_entities import async_expose_entity
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    floor_registry as fr,
)
from homeassistant.setup import async_setup_component


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load custom_components/ in every test."""


async def _home(hass: HomeAssistant) -> dict[str, Any]:
    """A small house: two floors, three rooms, a speaker in the kitchen."""
    assert await async_setup_component(hass, "homeassistant", {})
    floors, areas = fr.async_get(hass), ar.async_get(hass)
    ents, devs = er.async_get(hass), dr.async_get(hass)
    up = floors.async_create("Upstairs", aliases={"first floor"})
    kitchen = areas.async_create("Kitchen")
    bedroom = areas.async_create("Bedroom", floor_id=up.floor_id, aliases={"master"})
    study = areas.async_create("Study", floor_id=up.floor_id)
    entry = MockConfigEntry(domain="test")
    entry.add_to_hass(hass)

    def add(eid: str, state: str, area=None, name: str | None = None, expose=True, **attrs):
        domain, object_id = eid.split(".")
        reg = ents.async_get_or_create(domain, "test", object_id, suggested_object_id=object_id, config_entry=entry)
        if area is not None:
            ents.async_update_entity(reg.entity_id, area_id=area.id, **({"name": name} if name else {}))
        elif name:
            ents.async_update_entity(reg.entity_id, name=name)
        hass.states.async_set(eid, state, {"friendly_name": name or object_id.replace("_", " ").title(), **attrs})
        if expose:
            async_expose_entity(hass, "conversation", eid, True)
        else:
            async_expose_entity(hass, "conversation", eid, False)

    add("light.kitchen_lamp", "on", kitchen, "Kitchen Lamp", brightness=204)
    add("light.desk", "off", study, "Desk")
    add("light.bed", "on", bedroom, "Bed Light", brightness=102)
    add("light.hidden", "on", kitchen, "Hidden Light", expose=False)
    add("fan.ceiling", "on", bedroom, "Ceiling Fan", percentage=50, percentage_step=25)
    add("cover.garage", "closed", kitchen, "Garage Door", device_class="garage", current_position=0)
    add("cover.blind", "open", bedroom, "Blind", current_position=100)
    add("lock.front", "locked", kitchen, "Front Door")
    add("climate.hvac", "heat", bedroom, "Hvac", temperature=21, current_temperature=19.5)
    add("media_player.tv", "playing", kitchen, "Living Room Tv", volume_level=0.4)
    add("scene.movie", "unknown", kitchen, "Movie Night")
    add("vacuum.robot", "docked", kitchen, "Robot")
    add("alarm_control_panel.house", "disarmed", kitchen, "House")
    add("sensor.power", "100", kitchen, "Power", unit_of_measurement="W")
    speaker = devs.async_get_or_create(config_entry_id=entry.entry_id, identifiers={("thalovant", "1")}, name="Speaker")
    devs.async_update_device(speaker.id, area_id=kitchen.id)
    lone = devs.async_get_or_create(config_entry_id=entry.entry_id, identifiers={("thalovant", "2")}, name="Lone")
    return {"speaker": speaker.id, "lone": lone.id}


def action(capability: str, **target: Any) -> dict[str, Any]:
    value = target.pop("value", None)
    mode = target.pop("mode", None)
    out: dict[str, Any] = {"v": 1, "capability": capability, "target": target or {"here": True}}
    if value is not None:
        out["value"] = value
    if mode:
        out["mode"] = mode
    return out


async def test_names_are_compared_without_accents_or_case() -> None:
    assert fold("  Lumière  de la CUISINE! ") == "lumiere de la cuisine"


async def test_a_name_resolves_to_the_one_exposed_entity(hass: HomeAssistant) -> None:
    ids = await _home(hass)
    found = resolve(hass, action("brightness", name="kitchen lamp"), ids["speaker"])
    assert [s.entity_id for s in found] == ["light.kitchen_lamp"]


async def test_an_unexposed_entity_is_never_reached(hass: HomeAssistant) -> None:
    ids = await _home(hass)
    assert resolve(hass, action("power_off", name="hidden light"), ids["speaker"]) is None
    found = resolve(hass, action("power_off", area="kitchen", domain="light"), ids["speaker"])
    assert [s.entity_id for s in found] == ["light.kitchen_lamp"]


async def test_area_floor_alias_and_here(hass: HomeAssistant) -> None:
    ids = await _home(hass)
    by_floor = resolve(hass, action("power_off", floor="first floor", domain="light"), ids["speaker"])
    assert {s.entity_id for s in by_floor} == {"light.desk", "light.bed"}
    by_alias = resolve(hass, action("power_off", area="master", domain="light"), ids["speaker"])
    assert [s.entity_id for s in by_alias] == ["light.bed"]
    here = resolve(hass, action("power_off", here=True), ids["speaker"])
    assert [s.entity_id for s in here] == ["light.kitchen_lamp"]  # the speaker's room, lights only
    assert resolve(hass, action("power_off", here=True), ids["lone"]) is None  # a speaker with no room


async def test_two_entities_with_the_name_are_not_guessed(hass: HomeAssistant) -> None:
    ids = await _home(hass)
    ents = er.async_get(hass)
    reg = ents.async_get_or_create("light", "test", "second", suggested_object_id="second")
    ents.async_update_entity(reg.entity_id, name="Desk")
    hass.states.async_set("light.second", "off", {"friendly_name": "Desk"})
    async_expose_entity(hass, "conversation", "light.second", True)
    assert resolve(hass, action("power_on", name="desk"), ids["speaker"]) is None


async def test_a_capability_the_domain_lacks_is_not_resolved(hass: HomeAssistant) -> None:
    ids = await _home(hass)
    assert resolve(hass, action("brightness", name="ceiling fan"), ids["speaker"]) is None


async def test_brightness_relative_and_absolute(hass: HomeAssistant) -> None:
    ids = await _home(hass)
    calls = async_mock_service(hass, "light", "turn_on")
    assert await async_execute(hass, action("brightness", name="kitchen lamp", value=-20, mode="relative"), device_id=ids["speaker"])
    assert calls[-1].data["brightness_pct"] == 60  # 204/255 = 80 percent, minus 20
    assert await async_execute(hass, action("brightness", name="kitchen lamp", value=30, mode="absolute"), device_id=ids["speaker"])
    assert calls[-1].data["brightness_pct"] == 30


async def test_toggle_uses_the_domains_own_toggle(hass: HomeAssistant) -> None:
    ids = await _home(hass)
    calls = async_mock_service(hass, "light", "toggle")
    result = await async_execute(hass, action("toggle", name="desk"), device_id=ids["speaker"])
    assert result.speech_key == "action_done" and calls[0].data["entity_id"] == "light.desk"


async def test_temperature_relative_reads_the_setpoint(hass: HomeAssistant) -> None:
    ids = await _home(hass)
    calls = async_mock_service(hass, "climate", "set_temperature")
    assert await async_execute(hass, action("temperature", area="bedroom", domain="climate", value=1, mode="relative"), device_id=ids["speaker"])
    assert calls[0].data["temperature"] == 22.0  # setpoint 21 (not the 19.5 it measures) plus one


async def test_fan_speed_relative_steps_by_the_fans_own_step(hass: HomeAssistant) -> None:
    ids = await _home(hass)
    calls = async_mock_service(hass, "fan", "set_percentage")
    assert await async_execute(hass, action("fan_speed", name="ceiling fan", value=1, mode="relative"), device_id=ids["speaker"])
    assert calls[0].data["percentage"] == 75


async def test_volume_colour_colour_temperature_position(hass: HomeAssistant) -> None:
    ids = await _home(hass)
    vol = async_mock_service(hass, "media_player", "volume_set")
    assert await async_execute(hass, action("volume", name="living room tv", value=10, mode="relative"), device_id=ids["speaker"])
    assert vol[0].data["volume_level"] == 0.5
    light = async_mock_service(hass, "light", "turn_on")
    assert await async_execute(hass, action("color", name="bed light", value="red"), device_id=ids["speaker"])
    assert light[-1].data["rgb_color"] == [255, 0, 0]
    assert await async_execute(hass, action("color_temperature", name="bed light", value="warm white"), device_id=ids["speaker"])
    assert light[-1].data["color_temp_kelvin"] == 2700
    pos = async_mock_service(hass, "cover", "set_cover_position")
    assert await async_execute(hass, action("position", name="blind", value=50), device_id=ids["speaker"])
    assert pos[0].data["position"] == 50


async def test_scene_vacuum_and_a_state_read(hass: HomeAssistant) -> None:
    ids = await _home(hass)
    scene = async_mock_service(hass, "scene", "turn_on")
    assert await async_execute(hass, action("activate", name="movie night"), device_id=ids["speaker"])
    assert scene[0].data["entity_id"] == "scene.movie"
    vac = async_mock_service(hass, "vacuum", "start")
    assert await async_execute(hass, action("start", name="robot"), device_id=ids["speaker"])
    assert vac
    result = await async_execute(hass, action("state", name="power"), device_id=ids["speaker"])
    assert (result.response_type, result.placeholders) == ("query_answer", {"name": "Power", "state": "100 W"})


@pytest.mark.parametrize(
    ("capability", "target", "domain", "service"),
    [
        ("unlock", {"name": "front door"}, "lock", "unlock"),
        ("power_on", {"name": "garage door"}, "cover", "open_cover"),
        ("disarm", {"name": "house"}, "alarm_control_panel", "alarm_disarm"),
    ],
)
async def test_sensitive_actions_are_off_by_default(hass: HomeAssistant, capability, target, domain, service) -> None:
    ids = await _home(hass)
    calls = async_mock_service(hass, domain, service)
    assert await async_execute(hass, action(capability, **target), device_id=ids["speaker"], alarm_code="1234") is None
    assert not calls  # left to Assist as words: its own exposure rules decide


async def test_sensitive_actions_when_allowed_and_the_alarm_needs_its_code(hass: HomeAssistant) -> None:
    ids = await _home(hass)
    lock = async_mock_service(hass, "lock", "unlock")
    assert await async_execute(hass, action("unlock", name="front door"), device_id=ids["speaker"], allow_sensitive=True)
    assert lock
    alarm = async_mock_service(hass, "alarm_control_panel", "alarm_disarm")
    assert await async_execute(hass, action("disarm", name="house"), device_id=ids["speaker"], allow_sensitive=True) is None
    assert await async_execute(hass, action("disarm", name="house"), device_id=ids["speaker"], allow_sensitive=True, alarm_code="1234")
    assert alarm[0].data["code"] == "1234"


async def test_closing_a_garage_is_not_sensitive_but_opening_is(hass: HomeAssistant) -> None:
    ids = await _home(hass)
    close = async_mock_service(hass, "cover", "close_cover")
    assert await async_execute(hass, action("power_off", name="garage door"), device_id=ids["speaker"])
    assert close


async def test_a_failing_service_or_a_missing_one_goes_on_as_words(hass: HomeAssistant) -> None:
    ids = await _home(hass)
    assert await async_execute(hass, action("brightness", name="desk", value=30), device_id=ids["speaker"]) is None  # no service
    async_mock_service(hass, "light", "turn_on", raise_exception=RuntimeError("boom"))  # type: ignore[arg-type]
    assert await async_execute(hass, action("brightness", name="desk", value=30), device_id=ids["speaker"]) is None


async def test_an_unknown_capability_is_ignored(hass: HomeAssistant) -> None:
    await _home(hass)
    assert await async_execute(hass, {"v": 1, "capability": "explode", "target": {"name": "desk"}}, device_id=None) is None


async def test_a_name_that_is_no_entitys_is_read_as_an_area_then_a_floor(hass: HomeAssistant) -> None:
    ids = await _home(hass)
    area = resolve(hass, action("temperature", name="bedroom", domain="climate", value=1, mode="relative"), ids["speaker"])
    assert [s.entity_id for s in area] == ["climate.hvac"]
    floor = resolve(hass, action("power_off", name="upstairs", domain="light"), ids["speaker"])
    assert {s.entity_id for s in floor} == {"light.desk", "light.bed"}
    assert resolve(hass, action("power_off", name="nowhere", domain="light"), ids["speaker"]) is None


async def test_slower_never_switches_the_fan_off(hass: HomeAssistant) -> None:
    ids = await _home(hass)
    calls = async_mock_service(hass, "fan", "set_percentage")
    hass.states.async_set("fan.ceiling", "on", {"friendly_name": "Ceiling Fan", "percentage": 25, "percentage_step": 25})
    assert await async_execute(hass, action("fan_speed", name="ceiling fan", value=-1, mode="relative"), device_id=ids["speaker"])
    assert calls[0].data["percentage"] == 25
