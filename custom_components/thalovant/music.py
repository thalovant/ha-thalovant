"""Music actions: play and steer a household's Music Assistant players from the hub.

The hub's music skill sends the same structured ``action`` as the home skill
(``capability``, ``target``, ``value``) with a ``media`` object for what to
play. Music Assistant's players are media players in Home Assistant, so this
module resolves the target among *those* players only (names, aliases, areas;
exposed to Assist, never a Chromecast that happens to share a name) and calls
Home Assistant's own ``media_player`` and ``music_assistant`` actions. It never
dials Music Assistant itself and never sees its token.

What it does not do, so the request goes on as words (or is answered "not
found"): it never plays a raw URL (the media is always a name searched in the
household's own Music Assistant), never guesses between two players, and never
touches a player that is not exposed.

Players are found, in order, by the target the skill named, the speaker's own
room, a Music Assistant player named like the speaking device, and (for
"what's playing", shuffle and repeat only) the one player that is playing.
"""

from collections.abc import Mapping
from difflib import SequenceMatcher
from typing import Any

from homeassistant.core import Context, HomeAssistant, State
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .actions import ActionResult, async_execute, fold, resolve
from .const import LOGGER

MA_DOMAIN = "music_assistant"
MUSIC_CAPABILITIES = frozenset(
    {
        "play_media",
        "now_playing",
        "shuffle",
        "repeat",
        "transfer",
        "join",
        "unjoin",
    }
)
#: Capabilities the generic media builders already carry out; for them a Music
#: Assistant player is preferred when the target is the speaker's own room.
SHARED_CAPABILITIES = frozenset({"volume", "mute", "unmute", "playback"})
#: Where a search result lists each media type, best type first.
RESULT_KEYS = {
    "track": "tracks",
    "artist": "artists",
    "album": "albums",
    "playlist": "playlists",
    "radio": "radio",
}
#: A name closer than this to the query is not what was asked for.
MIN_MATCH = 0.6
#: Favourites queued at once.
FAVORITES = 50
ACTIVE = ("playing", "paused", "buffering")
REPEAT = {"off": "off", "one": "one", "all": "all"}


def _is_here(action: Mapping[str, Any]) -> bool:
    target = action.get("target") or {}
    return target.get("here") is True


def _device_name(hass: HomeAssistant, device_id: str | None) -> str:
    if not device_id or (device := dr.async_get(hass).async_get(device_id)) is None:
        return ""
    return device.name_by_user or device.name or ""


def music_player(
    hass: HomeAssistant,
    action: Mapping[str, Any],
    device_id: str | None,
    *,
    key: str = "target",
    allow_active: bool = False,
) -> State | None:
    """The one Music Assistant player the action means, or None."""
    found = resolve(hass, action, device_id, platform=MA_DOMAIN, key=key)
    if (found is None or len(found) != 1) and key == "target" and _is_here(action):
        # The speaker's room has no (single) Music Assistant player: a player named
        # like the speaker ("mark2" on the Mark II) is its own.
        if name := _device_name(hass, device_id):
            found = resolve(
                hass,
                {**action, "target": {"name": name}},
                device_id,
                platform=MA_DOMAIN,
            )
    if (found is None or len(found) != 1) and allow_active and _is_here(action):
        everyone = (
            resolve(
                hass,
                {**action, "target": {"all": True, "domain": "media_player"}},
                device_id,
                platform=MA_DOMAIN,
            )
            or []
        )
        found = [s for s in everyone if s.state in ACTIVE]
    return found[0] if found is not None and len(found) == 1 else None


def _score(query: str, name: str) -> float:
    """How well a result's name matches what was asked, 0 to 1."""
    wanted, got = fold(query), fold(name)
    if not wanted or not got:
        return 0.0
    if wanted == got:
        return 1.0
    ratio = SequenceMatcher(None, wanted, got).ratio()
    if set(wanted.split()) <= set(got.split()):
        ratio = max(ratio, 0.9)
    return ratio


def _artist_of(item: Mapping[str, Any]) -> str:
    artists = item.get("artists")
    if isinstance(artists, list) and artists and isinstance(artists[0], Mapping):
        return str(artists[0].get("name") or "")
    return ""


def best_match(
    results: Mapping[str, Any], media: Mapping[str, Any]
) -> dict[str, Any] | None:
    """The search result that is what the person asked for, or None.

    Names are compared folded; an artist named in the request breaks ties
    between versions of the same title, and the type order (track, artist,
    album, playlist, radio) breaks the rest.
    """
    query = media["query"]
    kinds = [media["type"]] if media.get("type") in RESULT_KEYS else list(RESULT_KEYS)
    artist = fold(media.get("artist"))
    best: tuple[float, int, dict[str, Any]] | None = None
    for rank, kind in enumerate(kinds):
        items = results.get(RESULT_KEYS[kind])
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, Mapping) or not isinstance(item.get("uri"), str):
                continue
            score = _score(query, str(item.get("name") or ""))
            if score < MIN_MATCH:
                continue
            if artist and (
                names := {fold(a.get("name")) for a in item.get("artists") or [] if a}
            ):
                if not any(artist in n or n in artist for n in names):
                    continue  # "by blink-182": another artist's song of the same name is not it
                score += 0.2
            if best is None or (score, -rank) > (best[0], -best[1]):
                best = (score, rank, {**item, "_kind": kind})
    return best[2] if best else None


async def _call(
    hass: HomeAssistant,
    domain: str,
    service: str,
    data: dict[str, Any],
    context: Context,
    *,
    response: bool = False,
) -> Any:
    return await hass.services.async_call(
        domain,
        service,
        data,
        blocking=True,
        context=context,
        return_response=response,
    )


def _name(state: State) -> str:
    return str(state.name)


async def async_execute_music(
    hass: HomeAssistant,
    action: Mapping[str, Any],
    *,
    device_id: str | None,
    context: Context | None = None,
    progress: list[str] | None = None,
) -> ActionResult | None:
    """Carry out a music action, or return None so the words go on to Assist.

    A player it cannot pin down is None; a player found but media that is not
    in the household's library, or a Music Assistant that failed, is an answer
    of its own, because the words would only search the same library again.
    """
    capability = action.get("capability")
    allow_active = capability in ("now_playing", "shuffle", "repeat")
    player = music_player(hass, action, device_id, allow_active=allow_active)
    if player is None:
        return None
    ctx = context or Context()
    done = progress if progress is not None else []
    try:
        return await _RUNNERS[str(capability)](
            hass, action, player, device_id, ctx, done
        )
    except TimeoutError:
        raise
    except Exception as err:  # noqa: BLE001 - never let the words repeat a half-done action
        LOGGER.debug(
            "Music %s on %s failed: %s",
            capability,
            player.entity_id,
            type(err).__name__,
        )
        return ActionResult(
            "error", "music_failed", {"player": _name(player)}, list(done)
        )


async def _now_playing(
    hass: HomeAssistant,
    action: Mapping[str, Any],
    player: State,
    device_id: str | None,
    ctx: Context,
    done: list[str],
) -> ActionResult:
    title = str(player.attributes.get("media_title") or "")
    if player.state not in ("playing", "paused") or not title:
        return ActionResult(
            "query_answer", "music_nothing_playing", {"player": _name(player)}
        )
    artist = str(player.attributes.get("media_artist") or "")
    paused = "paused" if player.state == "paused" else "playing"
    key = f"music_now_{paused}" + ("_by" if artist else "")
    return ActionResult(
        "query_answer", key, {"title": title, "artist": artist, "player": _name(player)}
    )


async def _play_media(
    hass: HomeAssistant,
    action: Mapping[str, Any],
    player: State,
    device_id: str | None,
    ctx: Context,
    done: list[str],
) -> ActionResult | None:
    media = action.get("media")
    if not isinstance(media, Mapping):
        return None
    needed = ["play_media"]
    if media.get("favorites"):
        needed += ["get_library"]
    elif media.get("similar"):
        needed += ["get_queue"]
    else:
        needed += ["search"]
    if any(not hass.services.has_service(MA_DOMAIN, n) for n in needed) or (
        media.get("favorites")
        and not hass.services.has_service("media_player", "shuffle_set")
    ):
        return None
    registered = er.async_get(hass).async_get(player.entity_id)
    entry_id = registered.config_entry_id if registered else None
    placeholders = {"player": _name(player), "query": str(media.get("query") or "")}
    play: dict[str, Any] = {"entity_id": player.entity_id}
    if media.get("favorites"):
        library = await _call(
            hass,
            MA_DOMAIN,
            "get_library",
            {
                "config_entry_id": entry_id,
                "media_type": "track",
                "favorite": True,
                "limit": FAVORITES,
            },
            ctx,
            response=True,
        )
        uris = [
            i["uri"]
            for i in (library or {}).get("items", [])
            if isinstance(i, Mapping) and isinstance(i.get("uri"), str)
        ]
        if not uris:
            return ActionResult("error", "music_no_favorites", placeholders)
        await _call(
            hass,
            MA_DOMAIN,
            "play_media",
            {**play, "media_id": uris, "media_type": "track", "enqueue": "replace"},
            ctx,
        )
        done.append(player.entity_id)
        await _call(
            hass,
            "media_player",
            "shuffle_set",
            {"entity_id": player.entity_id, "shuffle": True},
            ctx,
        )
        return ActionResult(
            "action_done", "music_favorites", placeholders, [player.entity_id]
        )
    if media.get("similar"):
        queue = await _call(
            hass,
            MA_DOMAIN,
            "get_queue",
            {"entity_id": player.entity_id},
            ctx,
            response=True,
        )
        current = ((queue or {}).get(player.entity_id) or {}).get("current_item") or {}
        item = current.get("media_item") or {}
        if not isinstance(item.get("uri"), str):
            return ActionResult("error", "music_nothing_playing", placeholders)
        await _call(
            hass,
            MA_DOMAIN,
            "play_media",
            {
                **play,
                "media_id": [item["uri"]],
                "enqueue": "replace",
                "radio_mode": True,
            },
            ctx,
        )
        done.append(player.entity_id)
        placeholders["title"] = str(current.get("name") or item.get("name") or "")
        return ActionResult(
            "action_done", "music_similar", placeholders, [player.entity_id]
        )
    kinds = [media["type"]] if media.get("type") in RESULT_KEYS else list(RESULT_KEYS)
    search: dict[str, Any] = {
        "config_entry_id": entry_id,
        "name": media["query"],
        "media_type": kinds,
        "limit": 8,
    }
    hit = None
    if media.get("artist"):
        # The artist narrows what the provider returns (a title many artists share would otherwise fill
        # the first results); if that finds nothing, the title alone is searched.
        results = await _call(
            hass,
            MA_DOMAIN,
            "search",
            {**search, "artist": media["artist"]},
            ctx,
            response=True,
        )
        hit = best_match(results or {}, media)
    if hit is None:
        results = await _call(hass, MA_DOMAIN, "search", search, ctx, response=True)
        hit = best_match(results or {}, media)
    if hit is None:
        return ActionResult("error", "music_not_found", placeholders)
    enqueue = media.get("enqueue") or "replace"
    await _call(
        hass,
        MA_DOMAIN,
        "play_media",
        {
            **play,
            "media_id": [hit["uri"]],
            "media_type": hit["_kind"],
            "enqueue": enqueue,
        },
        ctx,
    )
    done.append(player.entity_id)
    title, artist = str(hit.get("name") or ""), _artist_of(hit)
    placeholders.update(title=title, artist=artist)
    if enqueue == "next":
        key = "music_queued_next"
    elif enqueue == "add":
        key = "music_queued_add"
    else:
        key = "music_playing_by" if artist else "music_playing"
    return ActionResult("action_done", key, placeholders, [player.entity_id])


async def _shuffle(
    hass: HomeAssistant,
    action: Mapping[str, Any],
    player: State,
    device_id: str | None,
    ctx: Context,
    done: list[str],
) -> ActionResult | None:
    on = {"on": True, "off": False}.get(fold(action.get("value")))
    if on is None or not hass.services.has_service("media_player", "shuffle_set"):
        return None
    await _call(
        hass,
        "media_player",
        "shuffle_set",
        {"entity_id": player.entity_id, "shuffle": on},
        ctx,
    )
    return ActionResult(
        "action_done",
        "music_shuffle_on" if on else "music_shuffle_off",
        {"player": _name(player)},
        [player.entity_id],
    )


async def _repeat(
    hass: HomeAssistant,
    action: Mapping[str, Any],
    player: State,
    device_id: str | None,
    ctx: Context,
    done: list[str],
) -> ActionResult | None:
    mode = REPEAT.get(fold(action.get("value")))
    if mode is None or not hass.services.has_service("media_player", "repeat_set"):
        return None
    await _call(
        hass,
        "media_player",
        "repeat_set",
        {"entity_id": player.entity_id, "repeat": mode},
        ctx,
    )
    return ActionResult(
        "action_done",
        f"music_repeat_{mode}",
        {"player": _name(player)},
        [player.entity_id],
    )


async def _join(
    hass: HomeAssistant,
    action: Mapping[str, Any],
    player: State,
    device_id: str | None,
    ctx: Context,
    done: list[str],
) -> ActionResult | None:
    other = music_player(hass, action, device_id, key="other")
    if (
        other is None
        or other.entity_id == player.entity_id
        or not hass.services.has_service("media_player", "join")
    ):
        return None
    await _call(
        hass,
        "media_player",
        "join",
        {"entity_id": player.entity_id, "group_members": [other.entity_id]},
        ctx,
    )
    return ActionResult(
        "action_done",
        "music_joined",
        {"player": _name(player), "other": _name(other)},
        [player.entity_id, other.entity_id],
    )


async def _unjoin(
    hass: HomeAssistant,
    action: Mapping[str, Any],
    player: State,
    device_id: str | None,
    ctx: Context,
    done: list[str],
) -> ActionResult | None:
    if not hass.services.has_service("media_player", "unjoin"):
        return None
    await _call(hass, "media_player", "unjoin", {"entity_id": player.entity_id}, ctx)
    return ActionResult(
        "action_done", "music_unjoined", {"player": _name(player)}, [player.entity_id]
    )


async def _transfer(
    hass: HomeAssistant,
    action: Mapping[str, Any],
    player: State,
    device_id: str | None,
    ctx: Context,
    done: list[str],
) -> ActionResult | None:
    if not hass.services.has_service(MA_DOMAIN, "transfer_queue"):
        return None
    data: dict[str, Any] = {"entity_id": player.entity_id, "auto_play": True}
    if action.get("other"):
        source = music_player(hass, action, device_id, key="other")
        if source is None or source.entity_id == player.entity_id:
            return None
    else:
        # No source named: Home Assistant would take the first playing queue of the whole Music Assistant
        # server, exposed to Assist or not, in whatever order it lists them. Name the one exposed player
        # that is playing, or do not guess.
        exposed = (
            resolve(
                hass,
                {**action, "target": {"all": True, "domain": "media_player"}},
                device_id,
                platform=MA_DOMAIN,
            )
            or []
        )
        playing = [
            s for s in exposed if s.state == "playing" and s.entity_id != player.entity_id
        ]
        if len(playing) != 1:
            return None
        source = playing[0]
    data["source_player"] = source.entity_id
    await _call(hass, MA_DOMAIN, "transfer_queue", data, ctx)
    return ActionResult(
        "action_done",
        "music_transferred",
        {"player": _name(player)},
        [player.entity_id],
    )


_RUNNERS = {
    "play_media": _play_media,
    "now_playing": _now_playing,
    "shuffle": _shuffle,
    "repeat": _repeat,
    "join": _join,
    "unjoin": _unjoin,
    "transfer": _transfer,
}


async def async_execute_action(
    hass: HomeAssistant,
    action: Mapping[str, Any],
    *,
    device_id: str | None,
    allow_sensitive: bool = False,
    alarm_code: str | None = None,
    context: Context | None = None,
    progress: list[str] | None = None,
) -> ActionResult | None:
    """Carry out any structured action: music here, everything else in ``actions``.

    The shared media capabilities (volume, mute, playback) go to the speaker's own
    Music Assistant player first when the target is the speaker's room, so
    "turn the music up" reaches the player named like the speaker even in a
    house where that speaker has no area.
    """
    capability = action.get("capability")
    if capability in MUSIC_CAPABILITIES:
        return await async_execute_music(
            hass, action, device_id=device_id, context=context, progress=progress
        )
    target = action.get("target") or {}
    if (
        capability in SHARED_CAPABILITIES
        and target.get("here") is True
        and (player := music_player(hass, action, device_id))
    ):
        # the player already chosen, not its name again: a Chromecast called the same is exposed too
        return await async_execute(
            hass,
            action,
            device_id=device_id,
            allow_sensitive=allow_sensitive,
            alarm_code=alarm_code,
            context=context,
            progress=progress,
            states=[player],
        )
    return await async_execute(
        hass,
        action,
        device_id=device_id,
        allow_sensitive=allow_sensitive,
        alarm_code=alarm_code,
        context=context,
        progress=progress,
    )
