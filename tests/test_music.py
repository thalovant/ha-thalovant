"""Music actions: Music Assistant's players, as Home Assistant exposes them."""

import json
from pathlib import Path
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.thalovant.actions import async_execute
from custom_components.thalovant.music import (
    MA_DOMAIN,
    async_execute_action,
    async_execute_music,
    best_match,
    music_player,
)
from homeassistant.components.homeassistant.exposed_entities import async_expose_entity
from homeassistant.core import Context, HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.setup import async_setup_component

VECTORS = json.loads((Path(__file__).parent / "music_vectors.json").read_text())
WORLD = VECTORS["world"]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load custom_components/ in every test."""


class Fake:
    """Home Assistant's Music Assistant integration, as far as the actions go."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.fail: set[str] = set()
        self.ids: dict[str, str] = {}
        self.entry_id = ""
        self.device_ids: dict[str, str] = {}

    def effects(self) -> list[dict[str, Any]]:
        """The calls that change something, as the abstract effects the vectors name."""
        names = {v: k for k, v in self.ids.items()}
        out: list[dict[str, Any]] = []
        for _domain, service, data in self.calls:
            player = names.get(data.get("entity_id", ""), "")
            if service == "play_media":
                out.append(
                    {
                        "op": "play",
                        "player": player,
                        "uris": data["media_id"],
                        "type": data.get("media_type"),
                        "enqueue": data["enqueue"],
                        **({"radio": True} if data.get("radio_mode") else {}),
                    }
                )
            elif service == "shuffle_set":
                out.append({"op": "shuffle", "player": player, "on": data["shuffle"]})
            elif service == "repeat_set":
                out.append({"op": "repeat", "player": player, "mode": data["repeat"]})
            elif service == "join":
                out.append(
                    {
                        "op": "join",
                        "player": player,
                        "with": [names[m] for m in data["group_members"]],
                    }
                )
            elif service == "unjoin":
                out.append({"op": "unjoin", "player": player})
            elif service == "transfer_queue":
                out.append(
                    {
                        "op": "transfer",
                        "player": player,
                        "source": names.get(data.get("source_player", "")),
                    }
                )
        return out


async def _house(hass: HomeAssistant, with_services: bool = True) -> Fake:
    assert await async_setup_component(hass, "homeassistant", {})
    fake = Fake(hass)
    areas, ents, devs = ar.async_get(hass), er.async_get(hass), dr.async_get(hass)
    made = {name: areas.async_create(name) for name in ("Kitchen", "Bedroom")}
    ma_entry = MockConfigEntry(domain=MA_DOMAIN)
    ma_entry.add_to_hass(hass)
    fake.entry_id = ma_entry.entry_id
    other = MockConfigEntry(domain="cast")
    other.add_to_hass(hass)
    for player in WORLD["players"]:
        name = player["name"]
        object_id = name.lower()
        reg = ents.async_get_or_create(
            "media_player",
            MA_DOMAIN,
            f"ma-{object_id}",
            suggested_object_id=object_id,
            config_entry=ma_entry,
        )
        if player["area"]:
            ents.async_update_entity(reg.entity_id, area_id=made[player["area"]].id)
        attrs: dict[str, Any] = {"friendly_name": name}
        if player.get("title"):
            attrs["media_title"] = player["title"]
            attrs["media_artist"] = player["artist"]
        hass.states.async_set(reg.entity_id, player["state"], attrs)
        async_expose_entity(hass, "conversation", reg.entity_id, True)
        fake.ids[name] = reg.entity_id
    # a Chromecast that shares a Music Assistant player's name must never be reached
    cast = ents.async_get_or_create(
        "media_player",
        "cast",
        "cast-kitchen",
        suggested_object_id="kitchen_cast",
        config_entry=other,
    )
    hass.states.async_set(cast.entity_id, "idle", {"friendly_name": "Kitchen"})
    async_expose_entity(hass, "conversation", cast.entity_id, True)
    # an unexposed Music Assistant player
    hidden = ents.async_get_or_create(
        "media_player",
        MA_DOMAIN,
        "ma-hidden",
        suggested_object_id="hidden",
        config_entry=ma_entry,
    )
    hass.states.async_set(hidden.entity_id, "playing", {"friendly_name": "Hidden"})
    async_expose_entity(hass, "conversation", hidden.entity_id, False)
    for name, area in (
        ("kitchen speaker", "Kitchen"),
        ("mark2", None),
        ("somewhere else", None),
    ):
        device = devs.async_get_or_create(
            config_entry_id=other.entry_id, identifiers={("thalovant", name)}, name=name
        )
        if area:
            devs.async_update_device(device.id, area_id=made[area].id)
        fake.device_ids[name] = device.id

    if not with_services:
        return fake

    def record(domain: str, service: str) -> Any:
        async def handler(call: ServiceCall) -> Any:
            fake.calls.append((domain, service, dict(call.data)))
            if service in fake.fail:
                raise HomeAssistantError("boom")
            return None

        return handler

    for service in ("shuffle_set", "repeat_set", "join", "unjoin"):
        hass.services.async_register(
            "media_player", service, record("media_player", service)
        )
    hass.services.async_register(
        MA_DOMAIN, "play_media", record(MA_DOMAIN, "play_media")
    )
    hass.services.async_register(
        MA_DOMAIN, "transfer_queue", record(MA_DOMAIN, "transfer_queue")
    )

    async def search(call: ServiceCall) -> Any:
        fake.calls.append((MA_DOMAIN, "search", dict(call.data)))
        if "search" in fake.fail:
            raise HomeAssistantError("boom")
        return {
            k: WORLD["search"].get(k, [])
            for k in ("artists", "albums", "tracks", "playlists", "radio")
        }

    async def library(call: ServiceCall) -> Any:
        fake.calls.append((MA_DOMAIN, "get_library", dict(call.data)))
        return {"items": [{"uri": u} for u in fake.favorites]}

    async def queue(call: ServiceCall) -> Any:
        fake.calls.append((MA_DOMAIN, "get_queue", dict(call.data)))
        eid = fake.ids["Mark2"]
        return {
            eid: {
                "current_item": {
                    "name": "Blue",
                    "media_item": {"uri": WORLD["players"][1]["queue_uri"]},
                }
            }
        }

    fake.favorites = list(WORLD["favorites"])  # type: ignore[attr-defined]
    for name, func in (
        ("search", search),
        ("get_library", library),
        ("get_queue", queue),
    ):
        hass.services.async_register(
            MA_DOMAIN, name, func, supports_response=SupportsResponse.ONLY
        )
    return fake


def _shape(result: Any) -> Any:
    if result is None:
        return None
    return {
        "response_type": result.response_type,
        "speech_key": result.speech_key,
        "placeholders": result.placeholders,
    }


@pytest.mark.parametrize("case", VECTORS["cases"], ids=lambda c: c["name"])
async def test_the_shared_vectors(hass: HomeAssistant, case: dict[str, Any]) -> None:
    fake = await _house(hass)
    device = fake.device_ids[case.get("device_name", "kitchen speaker")]
    result = await async_execute_action(hass, case["action"], device_id=device)
    expect = case["expect"]
    if expect is None:
        assert result is None
        assert fake.effects() == []
        return
    assert result is not None
    got = _shape(result)
    assert got["response_type"] == expect["response_type"]
    assert got["speech_key"] == expect["speech_key"]
    for key, value in expect["placeholders"].items():
        assert got["placeholders"][key] == value
    assert fake.effects() == expect["effects"]


async def test_a_chromecast_with_the_same_name_is_not_a_music_player(
    hass: HomeAssistant,
) -> None:
    fake = await _house(hass)
    player = music_player(
        hass, {"capability": "now_playing", "target": {"name": "kitchen"}}, None
    )
    assert player is not None and player.entity_id == fake.ids["Kitchen"]


async def test_an_unexposed_player_is_never_reached(hass: HomeAssistant) -> None:
    await _house(hass)
    action = {"capability": "now_playing", "target": {"name": "hidden"}}
    assert music_player(hass, action, None) is None


async def test_a_failed_search_is_an_answer_not_the_words(hass: HomeAssistant) -> None:
    fake = await _house(hass)
    fake.fail.add("search")
    action = {
        "capability": "play_media",
        "target": {"name": "kitchen"},
        "media": {"query": "queen"},
    }
    progress: list[str] = []
    result = await async_execute_music(
        hass, action, device_id=None, context=Context(), progress=progress
    )
    assert result is not None and result.speech_key == "music_failed"
    assert result.response_type == "error" and progress == []


async def test_a_failure_after_the_music_started_keeps_what_was_done(
    hass: HomeAssistant,
) -> None:
    fake = await _house(hass)
    fake.fail.add("shuffle_set")
    action = {
        "capability": "play_media",
        "target": {"name": "mark2"},
        "media": {"favorites": True},
    }
    progress: list[str] = []
    result = await async_execute_music(hass, action, device_id=None, progress=progress)
    assert result is not None and result.speech_key == "music_failed"
    assert result.changed == progress == [fake.ids["Mark2"]]


async def test_a_timeout_is_not_swallowed(hass: HomeAssistant) -> None:
    fake = await _house(hass)

    async def slow(call: ServiceCall) -> Any:
        raise TimeoutError

    hass.services.async_register(MA_DOMAIN, "play_media", slow)
    action = {
        "capability": "play_media",
        "target": {"name": "kitchen"},
        "media": {"query": "queen"},
    }
    with pytest.raises(TimeoutError):
        await async_execute_music(hass, action, device_id=None)
    assert fake.ids


async def test_a_house_without_the_music_integration_is_left_to_the_words(
    hass: HomeAssistant,
) -> None:
    await _house(hass, with_services=False)
    for action in (
        {
            "capability": "play_media",
            "target": {"name": "kitchen"},
            "media": {"query": "queen"},
        },
        {
            "capability": "play_media",
            "target": {"name": "kitchen"},
            "media": {"favorites": True},
        },
        {
            "capability": "play_media",
            "target": {"name": "kitchen"},
            "media": {"similar": True},
        },
        {"capability": "shuffle", "value": "on", "target": {"name": "kitchen"}},
        {"capability": "repeat", "value": "all", "target": {"name": "kitchen"}},
        {
            "capability": "join",
            "target": {"name": "kitchen"},
            "other": {"name": "bedroom"},
        },
        {"capability": "unjoin", "target": {"name": "kitchen"}},
        {"capability": "transfer", "target": {"name": "kitchen"}},
    ):
        assert await async_execute_music(hass, action, device_id=None) is None


async def test_play_media_without_media_and_favorites_that_are_missing(
    hass: HomeAssistant,
) -> None:
    fake = await _house(hass)
    assert (
        await async_execute_music(
            hass,
            {"capability": "play_media", "target": {"name": "kitchen"}},
            device_id=None,
        )
        is None
    )
    fake.favorites.clear()  # type: ignore[attr-defined]
    result = await async_execute_music(
        hass,
        {
            "capability": "play_media",
            "target": {"name": "kitchen"},
            "media": {"favorites": True},
        },
        device_id=None,
    )
    assert result is not None and result.speech_key == "music_no_favorites"
    assert fake.effects() == []


async def test_more_like_this_with_nothing_playing(hass: HomeAssistant) -> None:
    fake = await _house(hass)

    async def empty(call: ServiceCall) -> Any:
        return {fake.ids["Kitchen"]: {"current_item": None}}

    hass.services.async_register(
        MA_DOMAIN, "get_queue", empty, supports_response=SupportsResponse.ONLY
    )
    result = await async_execute_music(
        hass,
        {
            "capability": "play_media",
            "target": {"name": "kitchen"},
            "media": {"similar": True},
        },
        device_id=None,
    )
    assert result is not None and result.speech_key == "music_nothing_playing"


async def test_a_paused_track_and_one_without_an_artist(hass: HomeAssistant) -> None:
    fake = await _house(hass)
    hass.states.async_set(
        fake.ids["Kitchen"],
        "paused",
        {"friendly_name": "Kitchen", "media_title": "Blue"},
    )
    result = await async_execute_music(
        hass,
        {"capability": "now_playing", "target": {"name": "kitchen"}},
        device_id=None,
    )
    assert result is not None and result.speech_key == "music_now_paused"
    hass.states.async_set(
        fake.ids["Kitchen"],
        "paused",
        {"friendly_name": "Kitchen", "media_title": "Blue", "media_artist": "X"},
    )
    result = await async_execute_music(
        hass,
        {"capability": "now_playing", "target": {"name": "kitchen"}},
        device_id=None,
    )
    assert result is not None and result.speech_key == "music_now_paused_by"


async def test_shuffle_and_transfer_refuse_what_they_cannot_read(
    hass: HomeAssistant,
) -> None:
    await _house(hass)
    for action in (
        {"capability": "shuffle", "value": "maybe", "target": {"name": "kitchen"}},
        {
            "capability": "transfer",
            "target": {"name": "kitchen"},
            "other": {"name": "garage"},
        },
        {
            "capability": "transfer",
            "target": {"name": "kitchen"},
            "other": {"name": "kitchen"},
        },
    ):
        assert await async_execute_music(hass, action, device_id=None) is None


async def test_the_dispatcher_sends_other_actions_to_the_home_path(
    hass: HomeAssistant,
) -> None:
    fake = await _house(hass)
    volume = async_mock_service(hass, "media_player", "volume_set")
    action = {
        "v": 1,
        "capability": "volume",
        "value": 30,
        "target": {"name": "kitchen", "domain": "media_player"},
    }
    # two exposed players are called Kitchen (a Chromecast too): the home path does not guess
    assert await async_execute_action(hass, action, device_id=None) is None
    assert volume == [] and fake.ids


async def test_volume_for_the_speaker_s_own_room_goes_to_its_music_player(
    hass: HomeAssistant,
) -> None:
    fake = await _house(hass)
    volume = async_mock_service(hass, "media_player", "volume_set")
    action = {"v": 1, "capability": "volume", "value": 30, "target": {"here": True}}
    result = await async_execute_action(
        hass, action, device_id=fake.device_ids["mark2"]
    )
    assert result is not None
    assert [c.data["entity_id"] for c in volume] == [fake.ids["Mark2"]]


async def test_the_plain_actions_module_still_ignores_music(
    hass: HomeAssistant,
) -> None:
    await _house(hass)
    assert (
        await async_execute(
            hass,
            {"capability": "play_media", "target": {"name": "kitchen"}},
            device_id=None,
        )
        is None
    )


async def test_best_match_skips_what_is_not_a_result() -> None:
    results = {
        "tracks": [None, {"uri": 1, "name": "queen"}, {"uri": "u", "name": "Queen"}],
        "artists": "x",
    }
    assert best_match(results, {"query": "queen"}) == {
        "uri": "u",
        "name": "Queen",
        "_kind": "track",
    }
    assert (
        best_match({"tracks": [{"uri": "u", "name": ""}]}, {"query": "queen"}) is None
    )
    assert best_match({}, {"query": "queen"}) is None
    assert (
        best_match(
            {"tracks": [{"uri": "u", "name": "x", "artists": [{}]}]}, {"query": ""}
        )
        is None
    )
    assert best_match(
        {"tracks": [{"uri": "u", "name": "q", "artists": None}]},
        {"query": "q", "artist": "z"},
    )


async def test_without_a_device_or_a_room_nothing_is_guessed(
    hass: HomeAssistant,
) -> None:
    await _house(hass)
    # the speaker is unknown and the target is not the speaker's room: no name, no playing fallback
    assert (
        music_player(
            hass,
            {"capability": "now_playing", "target": {"name": "garage"}},
            None,
            allow_active=True,
        )
        is None
    )
    # a speaker with no device has no room and no name: for a read, the one active player is the last resort
    action = {"capability": "now_playing", "target": {"here": True}}
    found = music_player(hass, action, None, allow_active=True)
    assert found is not None and found.name == "Mark2"
    assert music_player(hass, action, None) is None
