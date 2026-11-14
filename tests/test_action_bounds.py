"""What one structured action may reach: a room's lights, nothing sensitive unasked, no "all", a volume cap.

Each test here began as a proof of concept that passed against 0.4.0: "toggle the garage" toggled the
freezer plug and opened the door, a garage door with no device class opened with sensitive actions off,
``all`` reached every entity of a domain, and a volume of 100 was carried out as asked. They now assert
the fixed behaviour.
"""

from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.thalovant.actions import (
    SAFE_COVER_CLASSES,
    TARGET_KEYS,
    async_execute,
    exposed,
    is_known_action,
    max_volume_of,
    resolve,
)
from custom_components.thalovant.music import async_execute_action
from homeassistant.components.cover import CoverDeviceClass
from homeassistant.components.homeassistant.exposed_entities import async_expose_entity
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    floor_registry as fr,
)
from homeassistant.setup import async_setup_component

from .test_actions import refused


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load custom_components/ in every test."""


SERVICES = (
    ("light", "toggle"),
    ("switch", "toggle"),
    ("cover", "toggle"),
    ("light", "turn_off"),
    ("switch", "turn_off"),
    ("switch", "turn_on"),
    ("climate", "turn_off"),
    ("climate", "set_temperature"),
    ("media_player", "turn_off"),
    ("media_player", "volume_set"),
    ("cover", "open_cover"),
    ("cover", "close_cover"),
    ("cover", "set_cover_position"),
    ("script", "turn_on"),
    ("lock", "lock"),
    ("lock", "unlock"),
    ("alarm_control_panel", "alarm_arm_away"),
    ("alarm_control_panel", "alarm_disarm"),
)


async def _house(hass: HomeAssistant) -> dict[str, Any]:
    """A garage and a kitchen on one floor, with the things a garage really has."""
    assert await async_setup_component(hass, "homeassistant", {})
    floors, areas = fr.async_get(hass), ar.async_get(hass)
    ents, devs = er.async_get(hass), dr.async_get(hass)
    down = floors.async_create("Downstairs")
    garage = areas.async_create("Garage", floor_id=down.floor_id)
    kitchen = areas.async_create("Kitchen", floor_id=down.floor_id)
    entry = MockConfigEntry(domain="test")
    entry.add_to_hass(hass)

    def add(eid: str, state: str, area: ar.AreaEntry, name: str, **attrs: Any) -> None:
        domain, object_id = eid.split(".")
        reg = ents.async_get_or_create(
            domain, "test", object_id, suggested_object_id=object_id, config_entry=entry
        )
        ents.async_update_entity(reg.entity_id, area_id=area.id, name=name)
        hass.states.async_set(eid, state, {"friendly_name": name, **attrs})
        async_expose_entity(hass, "conversation", eid, True)

    add("light.garage_ceiling", "off", garage, "Garage Ceiling")
    add("switch.freezer", "on", garage, "Freezer")  # a plug nobody means to toggle
    add("switch.garage_opener", "off", garage, "Garage Opener")  # a relay: a DIY door
    # no device class: what a garage door from MQTT, ESPHome or a template usually is
    add("cover.garage_door", "closed", garage, "Big Door", current_position=0)
    add(
        "cover.side_gate",
        "closed",
        garage,
        "Side Gate",
        device_class="gate",
        current_position=0,
    )
    add("script.open_garage", "off", garage, "Open Up")
    add("light.kitchen", "on", kitchen, "Kitchen Light", brightness=200)
    add("switch.fridge", "on", kitchen, "Fridge")
    add("climate.kitchen", "heat", kitchen, "Kitchen Heating", temperature=20)
    add("media_player.kitchen", "playing", kitchen, "Kitchen Speaker", volume_level=0.2)
    add(
        "cover.kitchen_blind",
        "closed",
        kitchen,
        "Kitchen Blind",
        device_class="blind",
        current_position=0,
    )
    add("lock.front", "locked", kitchen, "Front Door")
    add("alarm_control_panel.house", "armed_away", kitchen, "House Alarm")
    speaker = devs.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("thalovant", "1")}, name="Speaker"
    )
    devs.async_update_device(speaker.id, area_id=kitchen.id)
    calls = {
        (domain, service): async_mock_service(hass, domain, service)
        for domain, service in SERVICES
    }
    return {"speaker": speaker.id, "calls": calls}


def _changed(calls: dict[tuple[str, str], list[ServiceCall]]) -> set[str]:
    return {c.data["entity_id"] for group in calls.values() for c in group}


# -- H1: a bare room or floor means its lights, whether it came as an area or as a name ----------


async def test_toggle_the_garage_toggles_its_lights_and_nothing_else(
    hass: HomeAssistant,
) -> None:
    """ "Toggle the garage" arrives as ``{capability: toggle, target: {name: "garage"}}``.

    No entity is called "garage", so the name is read as the area. It used to return every
    exposed light, switch, fan, input_boolean and cover in it: the freezer plug toggled and the
    door opened.
    """
    home = await _house(hass)
    result = await async_execute(
        hass,
        {"v": 1, "capability": "toggle", "target": {"name": "garage"}},
        device_id=home["speaker"],
        allow_sensitive=False,
    )
    assert result is not None and result.response_type == "action_done"
    assert _changed(home["calls"]) == {"light.garage_ceiling"}


async def test_a_floor_name_means_the_floors_lights(hass: HomeAssistant) -> None:
    home = await _house(hass)
    result = await async_execute(
        hass,
        {"v": 1, "capability": "toggle", "target": {"name": "downstairs"}},
        device_id=home["speaker"],
        allow_sensitive=True,  # even allowed, a floor is its lights
    )
    assert result is not None and result.response_type == "action_done"
    assert _changed(home["calls"]) == {"light.garage_ceiling", "light.kitchen"}


async def test_power_off_with_a_room_as_name_leaves_heating_plugs_and_players_alone(
    hass: HomeAssistant,
) -> None:
    home = await _house(hass)
    result = await async_execute(
        hass,
        {"v": 1, "capability": "power_off", "target": {"name": "kitchen"}},
        device_id=home["speaker"],
    )
    assert result is not None
    assert _changed(home["calls"]) == {"light.kitchen"}


async def test_a_room_as_name_and_a_room_as_area_mean_the_same(
    hass: HomeAssistant,
) -> None:
    home = await _house(hass)
    for capability in ("power_on", "power_off", "toggle"):
        as_name = resolve(
            hass,
            {"capability": capability, "target": {"name": "garage"}},
            home["speaker"],
        )
        as_area = resolve(
            hass,
            {"capability": capability, "target": {"area": "garage"}},
            home["speaker"],
        )
        assert as_name is not None and as_area is not None
        assert (
            [s.entity_id for s in as_name]
            == [s.entity_id for s in as_area]
            == ["light.garage_ceiling"]
        )


async def test_a_domain_named_with_the_room_is_still_honoured(
    hass: HomeAssistant,
) -> None:
    """The default is for a room named alone; "the kitchen plugs" says a domain."""
    home = await _house(hass)
    result = await async_execute(
        hass,
        {
            "v": 1,
            "capability": "power_off",
            "target": {"name": "kitchen", "domain": "switch"},
        },
        device_id=home["speaker"],
    )
    assert result is not None
    assert _changed(home["calls"]) == {"switch.fridge"}


async def test_a_capability_that_names_its_own_domain_is_not_narrowed_to_lights(
    hass: HomeAssistant,
) -> None:
    """ "Make the kitchen warmer" with no domain is still the kitchen's heating."""
    home = await _house(hass)
    result = await async_execute(
        hass,
        {
            "v": 1,
            "capability": "temperature",
            "target": {"name": "kitchen"},
            "value": 1,
            "mode": "relative",
        },
        device_id=home["speaker"],
    )
    assert result is not None
    assert _changed(home["calls"]) == {"climate.kitchen"}


# -- H2: a cover is sensitive unless it is a window covering; a refusal is an answer -------------


@pytest.mark.parametrize(
    ("action", "service"),
    [
        (
            {"capability": "power_on", "target": {"name": "big door"}},
            ("cover", "open_cover"),
        ),
        (
            {"capability": "toggle", "target": {"name": "big door"}},
            ("cover", "toggle"),
        ),
        (
            {"capability": "position", "target": {"name": "big door"}, "value": 100},
            ("cover", "set_cover_position"),
        ),
    ],
)
async def test_a_garage_door_with_no_device_class_does_not_open_with_sensitive_off(
    hass: HomeAssistant, action: dict[str, Any], service: tuple[str, str]
) -> None:
    """A garage door was known only by ``device_class``; one without a class opened."""
    home = await _house(hass)
    result = await async_execute(
        hass, {"v": 1, **action}, device_id=home["speaker"], allow_sensitive=False
    )
    assert refused(result)
    assert _changed(home["calls"]) == set()
    # the household that turned sensitive actions on still gets it
    result = await async_execute(
        hass, {"v": 1, **action}, device_id=home["speaker"], allow_sensitive=True
    )
    assert result is not None and result.response_type == "action_done"
    assert len(home["calls"][service]) == 1


async def test_closing_any_cover_and_moving_a_window_covering_are_not_sensitive(
    hass: HomeAssistant,
) -> None:
    home = await _house(hass)
    for action in (
        {"capability": "power_off", "target": {"name": "big door"}},
        {"capability": "power_on", "target": {"name": "kitchen blind"}},
        {"capability": "position", "target": {"name": "kitchen blind"}, "value": 40},
    ):
        result = await async_execute(hass, {"v": 1, **action}, device_id=None)
        assert result is not None and result.response_type == "action_done", action
    assert _changed(home["calls"]) == {"cover.garage_door", "cover.kitchen_blind"}


def test_the_safe_cover_classes_are_real_ones_and_never_a_way_in() -> None:
    """Every safe class exists in Home Assistant; a door, garage, gate or window never is one."""
    real = {c.value for c in CoverDeviceClass}
    assert real >= SAFE_COVER_CLASSES
    assert not SAFE_COVER_CLASSES & {"door", "garage", "gate", "window", "damper"}
    # a class Home Assistant adds later is sensitive until it is listed here
    assert real - SAFE_COVER_CLASSES == {"damper", "door", "garage", "gate", "window"}


@pytest.mark.parametrize(
    "action",
    [
        {"capability": "unlock", "target": {"name": "front door"}},
        {"capability": "lock", "target": {"name": "front door"}},
        {"capability": "disarm", "target": {"name": "house alarm"}},
        {"capability": "arm", "target": {"name": "house alarm"}},
        {"capability": "power_on", "target": {"name": "side gate"}},
        {"capability": "toggle", "target": {"name": "side gate"}},
        {"capability": "position", "target": {"name": "side gate"}, "value": 100},
        {"capability": "unlock", "target": {"area": "kitchen"}},
        # a sensitive verb that names what cannot be unlocked is still refused, not reworded
        {"capability": "unlock", "target": {"name": "front door", "domain": "light"}},
        {"capability": "power_on", "target": {"area": "garage", "domain": "cover"}},
    ],
)
async def test_a_sensitive_action_is_refused_aloud_when_sensitive_is_off(
    hass: HomeAssistant, action: dict[str, Any]
) -> None:
    """Refused as an answer, never as None: None hands the sentence to Assist, which can do it."""
    home = await _house(hass)
    result = await async_execute(
        hass,
        {"v": 1, **action},
        device_id=home["speaker"],
        allow_sensitive=False,
        alarm_code="1234",
    )
    assert refused(result)
    assert _changed(home["calls"]) == set()


async def test_with_sensitive_on_several_at_once_and_a_disarm_without_the_code_are_refused(
    hass: HomeAssistant,
) -> None:
    home = await _house(hass)
    # two covers that are sensitive to open, in one room
    result = await async_execute(
        hass,
        {
            "v": 1,
            "capability": "power_on",
            "target": {"area": "garage", "domain": "cover"},
        },
        device_id=home["speaker"],
        allow_sensitive=True,
    )
    assert refused(result, "action_sensitive_one")
    result = await async_execute(
        hass,
        {"v": 1, "capability": "disarm", "target": {"name": "house alarm"}},
        device_id=home["speaker"],
        allow_sensitive=True,
        alarm_code=None,
    )
    assert refused(result, "action_alarm_code")
    assert _changed(home["calls"]) == set()


async def test_known_limit_a_relay_or_a_script_named_exactly_is_carried_out(
    hass: HomeAssistant,
) -> None:
    """What cannot be classified: a relay is a switch like any other, a script runs anything.

    Named exactly and exposed to Assist, both are carried out with sensitive actions off (as
    Assist itself would). What protects them: a room or floor no longer sweeps them up, and an
    entity that is not exposed to Assist is never reached.
    """
    home = await _house(hass)
    for action, service in (
        (
            {"capability": "power_on", "target": {"name": "garage opener"}},
            ("switch", "turn_on"),
        ),
        (
            {"capability": "activate", "target": {"name": "open up"}},
            ("script", "turn_on"),
        ),
    ):
        result = await async_execute(hass, {"v": 1, **action}, device_id=None)
        assert result is not None and result.response_type == "action_done"
        assert len(home["calls"][service]) == 1
    for entity_id in ("switch.garage_opener", "script.open_garage"):
        async_expose_entity(hass, "conversation", entity_id, False)
    for action in (
        {"capability": "power_on", "target": {"name": "garage opener"}},
        {"capability": "activate", "target": {"name": "open up"}},
    ):
        assert await async_execute(hass, {"v": 1, **action}, device_id=None) is None
    assert len(home["calls"][("switch", "turn_on")]) == 1
    assert len(home["calls"][("script", "turn_on")]) == 1


# -- H3: the closed lists come first, and "all" is not a target -----------------------------------


@pytest.mark.parametrize(
    "action",
    [
        None,
        "toggle the lamp",
        ["toggle"],
        {},
        {"capability": None},
        {"capability": ["toggle"], "target": {"name": "kitchen light"}},
        {"capability": {"toggle": 1}, "target": {"name": "kitchen light"}},
        {"capability": "call_service", "target": {"name": "front door"}},
        {"capability": "toggle", "target": "kitchen light"},
        {"capability": "toggle", "target": ["kitchen light"]},
        {
            "capability": "toggle",
            "target": {"name": "kitchen light", "entity_id": "x.y"},
        },
        {"capability": "toggle", "target": {"all": True}},
        {"capability": "power_off", "target": {"all": True, "domain": "switch"}},
        {
            "capability": "power_off",
            "target": {"all": True, "area": "kitchen", "domain": "light"},
        },
        {
            "capability": "power_off",
            "target": {"name": "fridge", "domain": "shell_command"},
        },
        {"capability": "power_off", "target": {"name": "fridge", "domain": ["switch"]}},
        {"capability": "power_off", "target": {"name": "fridge", "domain": 7}},
        {
            "capability": "join",
            "target": {"name": "kitchen speaker"},
            "other": {"all": True},
        },
        {
            "capability": "join",
            "target": {"name": "kitchen speaker"},
            "other": "everything",
        },
    ],
)
async def test_an_action_outside_the_closed_lists_is_not_an_action(
    hass: HomeAssistant, action: Any
) -> None:
    """Checked before anything else: nothing is resolved, nothing is called, the words go on."""
    home = await _house(hass)
    assert is_known_action(action) is False
    assert resolve(hass, action, home["speaker"]) is None
    assert (
        await async_execute(
            hass, action, device_id=home["speaker"], allow_sensitive=True
        )
        is None
    )
    assert (
        await async_execute_action(
            hass, action, device_id=home["speaker"], allow_sensitive=True
        )
        is None
    )
    assert _changed(home["calls"]) == set()


def test_an_action_inside_the_lists_is_known() -> None:
    assert is_known_action({"capability": "toggle"})  # no target yet: resolved later
    assert is_known_action({"capability": "toggle", "target": None})
    assert is_known_action(
        {
            "v": 1,
            "capability": "join",
            "target": {"name": "a", "area": "b", "floor": "c", "here": False},
            "other": {"name": "d", "domain": "media_player"},
            "value": 3,
            "mode": "relative",
        }
    )
    assert {"name", "area", "floor", "domain", "here"} == TARGET_KEYS
    assert "all" not in TARGET_KEYS


async def test_everything_exposed_is_listed_only_from_inside(
    hass: HomeAssistant,
) -> None:
    """``exposed()`` is how this integration lists a domain itself; no target reaches it."""
    home = await _house(hass)
    async_expose_entity(hass, "conversation", "switch.fridge", False)
    assert {s.entity_id for s in exposed(hass, ("switch",))} == {
        "switch.freezer",
        "switch.garage_opener",
    }
    assert exposed(hass, ("switch",), platform="no_such_integration") == []
    assert len(exposed(hass, ())) == 12  # every exposed entity of the house
    assert _changed(home["calls"]) == set()


# -- H4: the volume cap -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "cap"),
    [
        (None, 100),
        (True, 100),
        ("50", 100),
        (0, 100),
        (-5, 100),
        (101, 100),
        (float("nan"), 100),
        (100, 100),
        (60, 60),
        (60.0, 60),
        (1, 1),
    ],
)
def test_the_cap_an_option_value_means(value: Any, cap: int) -> None:
    assert max_volume_of(value) == cap


async def test_without_a_cap_a_volume_of_100_is_carried_out(
    hass: HomeAssistant,
) -> None:
    home = await _house(hass)
    result = await async_execute(
        hass,
        {
            "v": 1,
            "capability": "volume",
            "target": {"name": "kitchen speaker"},
            "value": 100,
        },
        device_id=home["speaker"],
    )
    assert result is not None and result.speech_key == "action_done"
    assert home["calls"][("media_player", "volume_set")][0].data["volume_level"] == 1.0


@pytest.mark.parametrize(
    ("current", "value", "mode", "level", "capped"),
    [
        (0.2, 100, "absolute", 0.6, True),
        (0.2, 61, "absolute", 0.6, True),
        (0.2, 60, "absolute", 0.6, False),  # exactly the cap is not above it
        (0.2, 35, "absolute", 0.35, False),
        (0.2, 100, "relative", 0.6, True),
        (0.55, 10, "relative", 0.6, True),
        (0.2, 10, "relative", 0.3, False),
        # a player already above the cap: any structured volume brings it to the cap
        (0.9, 10, "relative", 0.6, True),
        (0.9, -10, "relative", 0.6, True),
        (0.9, -50, "relative", 0.4, False),
    ],
)
async def test_a_volume_above_the_cap_is_set_at_the_cap_and_said_so(
    hass: HomeAssistant,
    current: float,
    value: int,
    mode: str,
    level: float,
    capped: bool,
) -> None:
    home = await _house(hass)
    hass.states.async_set(
        "media_player.kitchen",
        "playing",
        {"friendly_name": "Kitchen Speaker", "volume_level": current},
    )
    result = await async_execute_action(
        hass,
        {
            "v": 1,
            "capability": "volume",
            "target": {"name": "kitchen speaker"},
            "value": value,
            "mode": mode,
        },
        device_id=home["speaker"],
        max_volume=60,
    )
    assert result is not None and result.response_type == "action_done"
    sent = home["calls"][("media_player", "volume_set")]
    assert [c.data["volume_level"] for c in sent] == [level]
    if capped:
        assert result.speech_key == "action_volume_capped"
        assert result.placeholders["level"] == "60"
    else:
        assert result.speech_key == "action_done"
