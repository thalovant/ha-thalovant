"""Tests for playing the hub's announcements on this Home Assistant's players."""

import asyncio
import logging
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.thalovant.api import HubMessage
from custom_components.thalovant.const import (
    CONF_ALLOW_RECEIVE,
    CONF_SELF_HOSTED,
    CONF_SPEAKER_AREAS,
    CONF_SPEAKER_PLAYERS,
    CONF_TTS_ENTITY,
    DOMAIN,
    SPEAK_MESSAGE_TYPE,
)
from custom_components.thalovant.models import ThalovantRuntimeData
from custom_components.thalovant.speaker import (
    IntercomSpeakerHandler,
    is_intercom_speak,
    parse_announcement,
)
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.util import dt as dt_util

from .conftest import ANNOUNCEMENT_ID, SECRET_TEXT, FakeHubConnection


def _speak_data(
    text: str = SECRET_TEXT,
    *,
    announcement_id: str = ANNOUNCEMENT_ID,
    priority: str = "normal",
    lang: str | None = "en-US",
    dialog: str = "intercom.announce",
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "utterance": text,
        "meta": {
            "dialog": dialog,
            "intercom": {"id": announcement_id, "priority": priority},
        },
    }
    if lang is not None:
        data["lang"] = lang
    return data


async def _settle(hass: HomeAssistant, delay: float = 0.0) -> None:
    """Let the background plays run. The connection's own task never ends, so
    waiting for every background task would wait forever."""
    await hass.async_block_till_done()
    for _ in range(30):
        await asyncio.sleep(delay)


class Room:
    """A running Home Assistant with one receiving entry and a fake tts.speak."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: MockConfigEntry,
        hub: FakeHubConnection,
        calls: list[ServiceCall],
    ) -> None:
        """Keep what the tests drive."""
        self.hass = hass
        self.entry = entry
        self.hub = hub
        self.calls = calls

    async def say(self, **kwargs: Any) -> None:
        """Deliver one announcement the way the hub sends it, and let it play."""
        await self.hub.emit(SPEAK_MESSAGE_TYPE, _speak_data(**kwargs))
        await _settle(self.hass)

    @property
    def received(self) -> dict[str, int]:
        """What the entry has counted."""
        return dict(self.entry.runtime_data.intercom_stats.received)


@pytest.fixture
async def room(
    hass: HomeAssistant,
    receive_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
) -> Room:
    """A receiving entry, one player, one text to speech, and a fake tts.speak."""
    hass.states.async_set("media_player.kitchen", "idle")
    hass.states.async_set("tts.piper", "unknown")
    calls = async_mock_service(hass, "tts", "speak")
    receive_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(receive_entry.entry_id)
    await hass.async_block_till_done()
    return Room(hass, receive_entry, mock_hub_connection, calls)


async def test_plays_on_the_players(
    room: Room, caplog: pytest.LogCaptureFixture
) -> None:
    """A valid announcement is played once, on the chosen player, uncached."""
    caplog.set_level(logging.DEBUG)
    volume = async_mock_service(room.hass, "media_player", "volume_set")

    await room.say()

    assert len(room.calls) == 1
    assert room.calls[0].data == {
        "entity_id": "tts.piper",
        "media_player_entity_id": ["media_player.kitchen"],
        "message": SECRET_TEXT,
        "cache": False,
    }
    assert room.received == {"played": 1}
    # An announcement is played at the player's own volume, urgent or not.
    assert volume == []
    # Only counters are recorded, and nothing logs the text.
    assert SECRET_TEXT not in caplog.text
    assert SECRET_TEXT not in repr(room.entry.runtime_data.intercom_stats)
    assert room.entry.runtime_data.intercom_stats.last_received_at is not None


async def test_urgent_does_not_touch_the_volume(room: Room) -> None:
    """Urgent changes nothing about the player: no volume, no unmute."""
    volume = async_mock_service(room.hass, "media_player", "volume_set")
    muted = async_mock_service(room.hass, "media_player", "volume_mute")
    await room.say(priority="urgent")
    assert len(room.calls) == 1
    assert volume == []
    assert muted == []


async def test_the_text_is_cleaned(room: Room) -> None:
    """Control characters and angle brackets never reach the text to speech."""
    await room.say(text="Hi\u202e <audio src=x>there\x07")
    assert room.calls[0].data["message"] == "Hi audio src=x there"


async def test_it_never_blocks_the_loop(room: Room) -> None:
    """The handler returns at once; a slow player is played in the background."""
    release = asyncio.Event()

    async def slow(call: ServiceCall) -> None:
        await release.wait()

    room.hass.services.async_register("tts", "speak", slow)
    await room.hub.emit(SPEAK_MESSAGE_TYPE, _speak_data())
    # The message came back before anything was played.
    assert room.received == {}
    release.set()
    await _settle(room.hass)
    assert room.received == {"played": 1}


@pytest.mark.parametrize(
    ("lang", "supported", "expected"),
    [
        ("fr", ["fr-FR", "en-US"], "fr-FR"),
        ("en-us", ["fr-FR", "en-US"], "en-US"),
        ("de", ["fr-FR", "en-US"], None),
        (None, ["fr-FR"], None),
        ("fr", None, None),
        ("not a language", ["fr-FR"], None),
    ],
)
async def test_language(
    room: Room, lang: str | None, supported: list[str] | None, expected: str | None
) -> None:
    """The closest language the engine speaks is asked for, else the engine's own."""
    if supported is not None:
        engine = MagicMock(supported_languages=supported)
        component = MagicMock()
        component.get_entity.return_value = engine
        room.hass.data["tts"] = component
    await room.say(lang=lang)
    assert len(room.calls) == 1
    assert room.calls[0].data.get("language") == expected


async def test_language_of_an_unknown_engine(room: Room) -> None:
    """An engine the tts component does not know is asked for its own language."""
    component = MagicMock()
    component.get_entity.return_value = None
    room.hass.data["tts"] = component
    await room.say(lang="fr")
    assert "language" not in room.calls[0].data


# --- What is ignored ---------------------------------------------------------


async def test_other_speech_is_not_ours(room: Room) -> None:
    """A speak message that is not an Intercom announcement is left alone, unseen."""
    await room.say(dialog="something.else")
    await room.hub.emit(SPEAK_MESSAGE_TYPE, {"utterance": "hello"})
    await room.hub.emit(SPEAK_MESSAGE_TYPE, {"utterance": "hi", "meta": "odd"})
    await room.hub.emit(SPEAK_MESSAGE_TYPE, [])  # type: ignore[arg-type]
    await _settle(room.hass)
    assert room.calls == []
    assert room.received == {}


@pytest.mark.parametrize(
    "data",
    [
        _speak_data(announcement_id="../x"),
        _speak_data(announcement_id=""),
        _speak_data(priority="loud"),
        _speak_data(text=""),
        _speak_data(text="\u202e\u200b"),
        _speak_data(text="x" * 281),
        {
            "meta": {
                "dialog": "intercom.announce",
                "intercom": {"id": "a", "priority": "normal"},
            }
        },
        {
            "utterance": 7,
            "meta": {
                "dialog": "intercom.announce",
                "intercom": {"id": "a", "priority": "normal"},
            },
        },
        {"utterance": "hi", "meta": {"dialog": "intercom.announce"}},
        {"utterance": "hi", "meta": {"dialog": "intercom.announce", "intercom": "odd"}},
    ],
)
async def test_invalid_announcements_are_ignored(
    room: Room, data: dict[str, Any]
) -> None:
    """An announcement that is not exactly the message is not played."""
    await room.hub.emit(SPEAK_MESSAGE_TYPE, data)
    await _settle(room.hass)
    assert room.calls == []
    assert room.received == {"ignored_invalid": 1}


async def test_per_minute_limit(room: Room) -> None:
    """Six new announcements a minute; the seventh is ignored, until the minute passes."""
    for number in range(6):
        await room.say(announcement_id=f"id-{number}")
    assert len(room.calls) == 6
    await room.say(announcement_id="id-6")
    assert len(room.calls) == 6
    assert room.received == {"played": 6, "ignored_rate_limited": 1}


async def test_repeats_of_an_urgent_announcement(room: Room) -> None:
    """An urgent announcement repeats as often as the platform lets it, no more."""
    for _ in range(10):
        await room.say(priority="urgent")
    assert len(room.calls) == 10
    await room.say(priority="urgent")
    assert len(room.calls) == 10
    assert room.received == {"played": 10, "ignored_repeated_too_often": 1}


async def test_a_normal_announcement_is_played_once(room: Room) -> None:
    """A normal announcement repeated by the hub is not played twice."""
    await room.say()
    await room.say()
    assert len(room.calls) == 1
    assert room.received == {"played": 1, "ignored_repeated_too_often": 1}


async def test_repeats_do_not_count_as_new(room: Room) -> None:
    """Repeats of one announcement never use up the per-minute allowance."""
    for _ in range(5):
        await room.say(priority="urgent")
    for number in range(5):
        await room.say(announcement_id=f"other-{number}")
    assert room.received == {"played": 10}


async def test_old_announcements_are_forgotten(room: Room) -> None:
    """Only the most recent announcements are remembered."""
    with (
        patch("custom_components.thalovant.speaker.RECEIVE_REMEMBERED", 2),
        patch("custom_components.thalovant.speaker.RECEIVE_PER_MINUTE", 100),
    ):
        handler = IntercomSpeakerHandler(room.hass, room.entry)
        for number in range(3):
            await room.hub.emit(
                SPEAK_MESSAGE_TYPE, _speak_data(announcement_id=f"x{number}")
            )
        assert handler is not None
    assert len(room.calls) == 3


async def test_no_players(room: Room) -> None:
    """A player that is unavailable or gone is not played on, and it is counted."""
    room.hass.states.async_set("media_player.kitchen", "unavailable")
    await room.say()
    room.hass.states.async_remove("media_player.kitchen")
    await room.say(announcement_id="second")
    assert room.calls == []
    assert room.received == {"ignored_no_players": 2}


async def test_the_available_player_is_used(
    room: Room,
) -> None:
    """Of several players, the unavailable one is skipped and each is named once."""
    room.hass.config_entries.async_update_entry(
        room.entry,
        options={
            **room.entry.options,
            CONF_SPEAKER_PLAYERS: [
                "media_player.kitchen",
                "media_player.kitchen",
                "media_player.gone",
                "media_player.out",
            ],
        },
    )
    room.hass.states.async_set("media_player.out", "unavailable")
    await room.hass.async_block_till_done()
    # The options changed: the entry reloads, with the new players.
    await _settle(room.hass)
    await room.hub.emit(SPEAK_MESSAGE_TYPE, _speak_data())
    await _settle(room.hass)
    assert room.calls[-1].data["media_player_entity_id"] == ["media_player.kitchen"]


async def test_areas(
    hass: HomeAssistant,
    receive_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
    area_registry: ar.AreaRegistry,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Every media player in a chosen area plays, once, by its own area or its device's."""
    area = area_registry.async_get_or_create("Salon")
    other = area_registry.async_get_or_create("Garage")
    receive_entry.add_to_hass(hass)
    device = device_registry.async_get_or_create(
        config_entry_id=receive_entry.entry_id,
        identifiers={("test", "tv")},
        name="TV",
    )
    device_registry.async_update_device(device.id, area_id=area.id)
    # By its own area.
    entity_registry.async_get_or_create(
        "media_player",
        "test",
        "own",
        suggested_object_id="own",
        original_name="Own",
        config_entry=receive_entry,
    )
    entity_registry.async_update_entity("media_player.own", area_id=area.id)
    # By its device's area.
    entity_registry.async_get_or_create(
        "media_player",
        "test",
        "tv",
        suggested_object_id="tv",
        config_entry=receive_entry,
        device_id=device.id,
    )
    # Its own area wins over its device's: this one is in the garage.
    entity_registry.async_get_or_create(
        "media_player",
        "test",
        "moved",
        suggested_object_id="moved",
        original_name="Moved",
        config_entry=receive_entry,
        device_id=device.id,
    )
    entity_registry.async_update_entity("media_player.moved", area_id=other.id)
    # Not a media player.
    entity_registry.async_get_or_create(
        "light",
        "test",
        "lamp",
        suggested_object_id="lamp",
        config_entry=receive_entry,
        device_id=device.id,
    )
    for entity_id in (
        "media_player.own",
        "media_player.tv",
        "media_player.moved",
        "light.lamp",
        "media_player.kitchen",
    ):
        hass.states.async_set(entity_id, "idle")
    hass.states.async_set("tts.piper", "unknown")
    hass.config_entries.async_update_entry(
        receive_entry,
        options={
            CONF_ALLOW_RECEIVE: True,
            CONF_SPEAKER_PLAYERS: ["media_player.kitchen"],
            CONF_SPEAKER_AREAS: [area.id],
        },
    )
    calls = async_mock_service(hass, "tts", "speak")
    assert await hass.config_entries.async_setup(receive_entry.entry_id)
    await hass.async_block_till_done()

    await mock_hub_connection.emit(SPEAK_MESSAGE_TYPE, _speak_data())
    await _settle(hass)

    assert calls[0].data["media_player_entity_id"] == [
        "media_player.kitchen",
        "media_player.own",
        "media_player.tv",
    ]


# --- The text to speech ------------------------------------------------------


async def test_the_chosen_tts_is_used(room: Room) -> None:
    """A text to speech chosen in the options is the one used."""
    room.hass.states.async_set("tts.other", "unknown")
    room.hass.config_entries.async_update_entry(
        room.entry, options={**room.entry.options, CONF_TTS_ENTITY: "tts.other"}
    )
    await room.hass.async_block_till_done()
    await _settle(room.hass)
    await room.hub.emit(SPEAK_MESSAGE_TYPE, _speak_data())
    await _settle(room.hass)
    assert room.calls[-1].data["entity_id"] == "tts.other"


async def test_a_missing_tts_is_not_replaced(room: Room) -> None:
    """A chosen text to speech that is gone plays nothing, rather than another voice."""
    room.hass.config_entries.async_update_entry(
        room.entry, options={**room.entry.options, CONF_TTS_ENTITY: "tts.gone"}
    )
    await room.hass.async_block_till_done()
    await _settle(room.hass)
    await room.hub.emit(SPEAK_MESSAGE_TYPE, _speak_data())
    await _settle(room.hass)
    assert room.calls == []
    assert room.received == {"ignored_no_tts": 1}


async def test_default_tts(room: Room, entity_registry: er.EntityRegistry) -> None:
    """The default is the cloud's when there is one, else the first that is up."""
    room.hass.states.async_set("tts.piper", "unavailable")
    await room.say()
    assert room.calls == []
    assert room.received == {"ignored_no_tts": 1}

    room.hass.states.async_set("tts.zeta", "unknown")
    room.hass.states.async_set("tts.alpha", "unknown")
    await room.say(announcement_id="b")
    assert room.calls[-1].data["entity_id"] == "tts.alpha"

    entity_registry.async_get_or_create(
        "tts", "cloud", "voice", suggested_object_id="cloud_voice"
    )
    room.hass.states.async_set("tts.cloud_voice", "unknown")
    await room.say(announcement_id="c")
    assert room.calls[-1].data["entity_id"] == "tts.cloud_voice"


# --- Failures ----------------------------------------------------------------


async def test_a_failed_play_is_counted(
    room: Room, caplog: pytest.LogCaptureFixture
) -> None:
    """A text to speech that fails is a counted failure, typed in the log."""
    caplog.set_level(logging.DEBUG)

    async def failing(call: ServiceCall) -> None:
        raise RuntimeError(call.data["message"])

    room.hass.services.async_register("tts", "speak", failing)
    await room.say()
    assert room.received == {"play_failed": 1}
    assert "RuntimeError" in caplog.text
    assert SECRET_TEXT not in caplog.text
    assert room.entry.runtime_data.intercom_stats is not None


async def test_a_play_that_takes_too_long(room: Room) -> None:
    """A player that never answers is given up on."""

    async def hanging(call: ServiceCall) -> None:
        await asyncio.sleep(3600)

    room.hass.services.async_register("tts", "speak", hanging)
    with patch("custom_components.thalovant.speaker.PLAY_TIMEOUT", 0.01):
        await room.hub.emit(SPEAK_MESSAGE_TYPE, _speak_data())
        await _settle(room.hass, 0.002)
    assert room.received == {"play_failed": 1}


async def test_too_many_plays_at_once(room: Room) -> None:
    """At most four plays run at once; the next is ignored, not queued."""
    release = asyncio.Event()

    async def slow(call: ServiceCall) -> None:
        await release.wait()

    room.hass.services.async_register("tts", "speak", slow)
    for number in range(5):
        await room.hub.emit(
            SPEAK_MESSAGE_TYPE, _speak_data(announcement_id=f"id-{number}")
        )
    assert room.received == {"ignored_busy": 1}
    release.set()
    await _settle(room.hass)
    assert room.received == {"ignored_busy": 1, "played": 4}


# --- Setup and the private link -------------------------------------------


async def test_only_subscribed_when_on(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
) -> None:
    """Without the option the entry does not listen for speak at all."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert SPEAK_MESSAGE_TYPE not in mock_hub_connection.message_callbacks


async def test_unload_unsubscribes(room: Room) -> None:
    """Unloading stops listening."""
    assert len(room.hub.message_callbacks[SPEAK_MESSAGE_TYPE]) == 1
    assert await room.hass.config_entries.async_unload(room.entry.entry_id)
    assert room.hub.message_callbacks[SPEAK_MESSAGE_TYPE] == []


async def test_a_private_link_never_plays(hass: HomeAssistant) -> None:
    """A private hub has no such grant and its handler admits one request only."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_SELF_HOSTED: True},
        options={CONF_SPEAKER_PLAYERS: ["media_player.kitchen"]},
    )
    entry.add_to_hass(hass)
    entry.runtime_data = ThalovantRuntimeData(connection=MagicMock())
    hass.states.async_set("media_player.kitchen", "idle")
    hass.states.async_set("tts.piper", "unknown")
    calls = async_mock_service(hass, "tts", "speak")
    handler = IntercomSpeakerHandler(hass, entry)
    handler.async_handle_message(HubMessage(SPEAK_MESSAGE_TYPE, _speak_data(), {}))
    await _settle(hass)
    assert calls == []
    assert dict(entry.runtime_data.intercom_stats.received) == {
        "ignored_self_hosted": 1
    }


def test_parse_announcement() -> None:
    """The shape of a valid announcement, and the rest."""
    message = HubMessage(SPEAK_MESSAGE_TYPE, _speak_data(lang="fr_ca"), {})
    parsed = parse_announcement(message)
    assert parsed is not None
    assert (parsed.announcement_id, parsed.priority, parsed.language) == (
        ANNOUNCEMENT_ID,
        "normal",
        "fr-CA",
    )
    # The text is not in its repr.
    assert SECRET_TEXT not in repr(parsed)
    assert parse_announcement(HubMessage("other", _speak_data(), {})) is None
    assert parse_announcement(HubMessage(SPEAK_MESSAGE_TYPE, {"meta": 1}, {})) is None
    odd = parse_announcement(
        HubMessage(SPEAK_MESSAGE_TYPE, _speak_data(lang="x" * 40), {})
    )
    assert odd is not None
    assert odd.language is None
    assert is_intercom_speak(message)
    assert not is_intercom_speak(HubMessage(SPEAK_MESSAGE_TYPE, {}, {}))
    assert dt_util.utcnow() is not None
