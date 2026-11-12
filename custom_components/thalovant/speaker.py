"""Home Assistant as a speaker: play the hub's announcements on media players.

When the options turn receiving on, the hub may ask this Home Assistant to say
an announcement. The hub sends an ordinary ``speak`` message whose ``meta.dialog``
is ``intercom.announce`` and whose ``meta.intercom`` holds the announcement's id
and priority. This module accepts such a message, checks it, and says its text
on the chosen media players with Home Assistant's ``tts.speak``.

What it will not do:

* Play anything that is not exactly that message, from anything but the hub's
  authenticated link. A private (self-hosted) link never plays: its hub has no
  such grant, and its handler admits one lighting request only.
* Play more than a handful of announcements a minute, or one announcement more
  often than the platform lets it repeat.
* Change a volume. An urgent announcement is played at the player's own volume.
* Block the event loop (every play is its own background task), or log, store
  or count the text. Only counters reach diagnostics.

It is a convenience, not a certified safety system, and it does not replace
smoke or carbon monoxide alarms, medical alert devices or emergency services.
"""

import asyncio
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, field
import re
from typing import Any

from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import Context, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util, language as language_util

from .api import HubMessage
from .const import (
    CONF_SELF_HOSTED,
    CONF_SPEAKER_AREAS,
    CONF_SPEAKER_PLAYERS,
    CONF_TTS_ENTITY,
    DOMAIN,
    INTERCOM_DIALOG,
    LOGGER,
    MAX_REPEAT_TIMES,
    PLAY_TIMEOUT,
    RECEIVE_MAX_IN_FLIGHT,
    RECEIVE_PER_MINUTE,
    RECEIVE_REMEMBERED,
    SPEAK_MESSAGE_TYPE,
)
from .handler import canonical_language
from .intercom import SlidingWindowLimiter, clean_received_text
from .models import ThalovantConfigEntry

_ANNOUNCEMENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}")
_LANGUAGE = re.compile(r"[A-Za-z]{2,3}(?:[-_][A-Za-z0-9]{1,8}){0,3}")
_PRIORITIES = frozenset({"normal", "urgent"})

# What became of an announcement the hub asked this Home Assistant to play.
OUTCOME_PLAYED = "played"
OUTCOME_FAILED = "play_failed"
OUTCOME_INVALID = "ignored_invalid"
OUTCOME_RATE_LIMITED = "ignored_rate_limited"
OUTCOME_REPEATED_TOO_OFTEN = "ignored_repeated_too_often"
OUTCOME_NO_PLAYERS = "ignored_no_players"
OUTCOME_NO_TTS = "ignored_no_tts"
OUTCOME_BUSY = "ignored_busy"
OUTCOME_SELF_HOSTED = "ignored_self_hosted"


@dataclass(frozen=True, slots=True)
class ReceivedAnnouncement:
    """A checked announcement from the hub. The text is never in its repr."""

    announcement_id: str
    priority: str
    text: str = field(repr=False)
    language: str | None


def parse_announcement(message: HubMessage) -> ReceivedAnnouncement | None:
    """The announcement a speak message carries, or None for anything else.

    Exactly a ``speak`` message whose ``meta.dialog`` is ``intercom.announce``,
    with an announcement id of a safe shape, a priority of normal or urgent and
    a text that is fit to say once cleaned. Anything short of that is None.
    """
    data: object = message.data
    if message.type != SPEAK_MESSAGE_TYPE or not isinstance(data, Mapping):
        return None
    meta = data.get("meta")
    if not isinstance(meta, Mapping) or meta.get("dialog") != INTERCOM_DIALOG:
        return None
    intercom = meta.get("intercom")
    if not isinstance(intercom, Mapping):
        return None
    announcement_id = intercom.get("id")
    priority = intercom.get("priority")
    utterance = data.get("utterance")
    if (
        not isinstance(announcement_id, str)
        or _ANNOUNCEMENT_ID.fullmatch(announcement_id) is None
        or priority not in _PRIORITIES
        or not isinstance(utterance, str)
    ):
        return None
    text = clean_received_text(utterance)
    if text is None:
        return None
    lang = data.get("lang")
    language = (
        canonical_language(lang)
        if isinstance(lang, str)
        and len(lang) <= 35
        and _LANGUAGE.fullmatch(lang.strip()) is not None
        else None
    )
    return ReceivedAnnouncement(announcement_id, priority, text, language)


def is_intercom_speak(message: HubMessage) -> bool:
    """Whether a message claims to be an Intercom announcement, valid or not."""
    data: object = message.data
    if not isinstance(data, Mapping):
        return False
    meta = data.get("meta")
    return isinstance(meta, Mapping) and meta.get("dialog") == INTERCOM_DIALOG


class IntercomSpeakerHandler:
    """Plays the announcements the hub sends to one config entry.

    One instance per entry that has receiving on, subscribed to the entry's hub
    connection, which only the hub can speak on.
    """

    def __init__(self, hass: HomeAssistant, entry: ThalovantConfigEntry) -> None:
        """Prepare the limits; nothing is played."""
        self._hass = hass
        self._entry = entry
        self._self_hosted = entry.data.get(CONF_SELF_HOSTED) is True
        self._new = SlidingWindowLimiter(RECEIVE_PER_MINUTE, 60.0)
        # id -> (how often it may still be played): the most recent ones.
        self._plays_left: OrderedDict[str, int] = OrderedDict()
        self._in_flight = 0

    @callback
    def async_handle_message(self, message: HubMessage) -> None:
        """Take a speak message off the connection's receive path.

        Only checks and counting happen here; playing is a background task, so
        a slow media player never holds up the connection.
        """
        if not is_intercom_speak(message):
            return
        if self._self_hosted:
            self._record(OUTCOME_SELF_HOSTED)
            return
        announcement = parse_announcement(message)
        if announcement is None:
            self._record(OUTCOME_INVALID)
            return
        if (outcome := self._admit(announcement)) is not None:
            self._record(outcome)
            return
        players = self._async_players()
        if not players:
            self._record(OUTCOME_NO_PLAYERS)
            return
        if (tts_entity := self._async_tts_entity()) is None:
            self._record(OUTCOME_NO_TTS)
            return
        if self._in_flight >= RECEIVE_MAX_IN_FLIGHT:
            self._record(OUTCOME_BUSY)
            return
        self._in_flight += 1
        self._entry.async_create_background_task(
            self._hass,
            self._async_play(announcement, players, tts_entity),
            name=f"{DOMAIN} play announcement",
        )

    def _admit(self, announcement: ReceivedAnnouncement) -> str | None:
        """The reason an announcement is not played now, or None to go ahead.

        A new announcement counts against the per-minute limit. One already
        known may be played again (an urgent one repeats), but only as often
        as the platform lets that kind repeat: once when normal.
        """
        left = self._plays_left.get(announcement.announcement_id)
        if left is None:
            if not self._new.allow():
                return OUTCOME_RATE_LIMITED
            left = MAX_REPEAT_TIMES if announcement.priority == "urgent" else 1
        if left <= 0:
            return OUTCOME_REPEATED_TOO_OFTEN
        self._plays_left[announcement.announcement_id] = left - 1
        self._plays_left.move_to_end(announcement.announcement_id)
        while len(self._plays_left) > RECEIVE_REMEMBERED:
            self._plays_left.popitem(last=False)
        return None

    @callback
    def _async_players(self) -> list[str]:
        """The media players to play on that exist and are not unavailable.

        The chosen players, then every media player in each chosen area (its
        own area, or its device's when it has none), each once.
        """
        options = self._entry.options
        chosen: list[str] = list(options.get(CONF_SPEAKER_PLAYERS, []))
        entities = er.async_get(self._hass)
        devices = dr.async_get(self._hass)
        for area_id in options.get(CONF_SPEAKER_AREAS, []):
            chosen.extend(
                entity.entity_id
                for entity in er.async_entries_for_area(entities, area_id)
                if entity.domain == "media_player"
            )
            for device in dr.async_entries_for_area(devices, area_id):
                chosen.extend(
                    entity.entity_id
                    for entity in er.async_entries_for_device(entities, device.id)
                    if entity.domain == "media_player" and entity.area_id is None
                )
        players: list[str] = []
        for entity_id in chosen:
            state = self._hass.states.get(entity_id)
            if (
                state is not None
                and state.state != STATE_UNAVAILABLE
                and entity_id not in players
            ):
                players.append(entity_id)
        return players

    @callback
    def _async_tts_entity(self) -> str | None:
        """The text to speech entity to use: the chosen one, else the default.

        The default is Home Assistant's own rule (the cloud's when there is
        one, else the first), read from the registry: the tts integration is
        never imported here, because it brings requirements of its own that a
        Home Assistant without a text to speech engine does not have.
        """
        chosen = self._entry.options.get(CONF_TTS_ENTITY)
        if isinstance(chosen, str) and chosen:
            return chosen if self._hass.states.get(chosen) is not None else None
        usable = sorted(
            entity_id
            for entity_id in self._hass.states.async_entity_ids("tts")
            if (state := self._hass.states.get(entity_id)) is not None
            and state.state != STATE_UNAVAILABLE
        )
        registry = er.async_get(self._hass)
        for entity_id in usable:
            if (entry := registry.async_get(entity_id)) and entry.platform == "cloud":
                return entity_id
        return usable[0] if usable else None

    @callback
    def _async_language(self, tts_entity: str, language: str | None) -> str | None:
        """The closest language the engine speaks, or None for the engine's own.

        The engine is read from the tts component's data when it is there; an
        engine that cannot be found is asked for its own language rather than
        one it may refuse.
        """
        component = self._hass.data.get("tts")
        engine = component.get_entity(tts_entity) if component is not None else None
        if language is None or engine is None:
            return None
        matches = language_util.matches(
            language, engine.supported_languages, country=self._hass.config.country
        )
        return matches[0] if matches else None

    async def _async_play(
        self,
        announcement: ReceivedAnnouncement,
        players: list[str],
        tts_entity: str,
    ) -> None:
        """Say the text on the players, once. Never raises, never logs the text."""
        data: dict[str, Any] = {
            "entity_id": tts_entity,
            "media_player_entity_id": players,
            "message": announcement.text,
            # A spoken announcement is not kept: no audio file of it is cached.
            "cache": False,
        }
        if language := self._async_language(tts_entity, announcement.language):
            data["language"] = language
        outcome = OUTCOME_PLAYED
        try:
            async with asyncio.timeout(PLAY_TIMEOUT):
                await self._hass.services.async_call(
                    "tts", "speak", data, blocking=True, context=Context()
                )
        except Exception as err:  # noqa: BLE001 - a failed play is counted, not raised
            outcome = OUTCOME_FAILED
            LOGGER.warning(
                "Could not play announcement %s (%s)",
                announcement.announcement_id,
                type(err).__name__,
            )
        finally:
            self._in_flight -= 1
        LOGGER.debug(
            "Announcement %s %s on %d player(s)",
            announcement.announcement_id,
            outcome,
            len(players),
        )
        self._record(outcome)

    def _record(self, outcome: str) -> None:
        """Count one outcome. Counters are all diagnostics ever hold."""
        self._entry.runtime_data.intercom_stats.record_received(
            outcome, dt_util.utcnow()
        )
