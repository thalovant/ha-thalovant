Last Edit: Claude Sonnet 5.5 - 2026-11-13 - Motive: documentation sweep: cross-checked against music.py (removed a class name that does not exist, the conditions on the player fallbacks, the shared controls that reach any exposed media player by name, shuffle and repeat values, answers for nothing playing and no favorites, the vector files), status: on main after v0.4.0, not released.

# Music through Home Assistant

If your household runs Music Assistant behind Home Assistant (the *Music Assistant* integration), your Thalovant devices can play and steer it **through the Home Assistant link you already have**: no second connection, no open port, no Music Assistant token on the hub.

```
device -> hub -> thalovant-skill-music-assistant -> thalovant.home.request {action}
       -> hivemind-home-router (your household only) -> this integration (custom_components/thalovant/music.py)
       -> Home Assistant: music_assistant.search / play_media, media_player.* -> Music Assistant
```

## What it does

**Status.** Merged on `main` (pull request #31) after the `v0.4.0` release; `manifest.json` still says 0.4.0, so a HACS install of 0.4.0 does not have it. Home Assistant 2026.10.4 and the Music Assistant integration's services were read for this page; a live check against a real Music Assistant server is the author's, recorded in [MAINTENANCE_REPORT.md](../MAINTENANCE_REPORT.md), and was not repeated by the documentation sweep.

Which route a music request takes is decided on the hub, by the music skill's media library: the household's home-bridge connection when it is online, else this Home Assistant link, else a direct connection (`choose_route()` in `[thalovant-media-core: thalovant_media_core/connector.py]`, mode `auto`, the skill passes `ha_capable=True`). This page is about the Home Assistant route. See also `[thalovant-skill-music-assistant: README.md]`.

Music actions are `capability` + `target` (+ `media`, `value`, `other`):

| Capability | Done with |
|---|---|
| `play_media` (`media`: `query`, `type` track/album/artist/playlist/radio, `artist`, `enqueue` play/replace/next/add; no `enqueue` means replace) | `music_assistant.search` (the best name match across your library and your providers, narrowed by the artist when you name one, never a raw URL), then `music_assistant.play_media`. The spec's `media.album` is accepted by the router but this integration does not read it |
| `play_media` with `favorites` | `music_assistant.get_library` (up to 50 favorite tracks), `play_media`, then `media_player.shuffle_set` once playback has started. No favorites: "You have no favorites to play." |
| `play_media` with `similar` | `music_assistant.get_queue` (the current track), then `play_media` with radio mode. Nothing playing: "Nothing is playing on {player}." |
| `now_playing` | the player's `media_title` / `media_artist` / state (playing or paused; otherwise "Nothing is playing on {player}.") |
| `shuffle` (`value` on/off), `repeat` (`value` off/one/all) | `media_player.shuffle_set`, `repeat_set`. Any other value is not carried out and the request goes on as words |
| `transfer` (`other` = the source; without it, the one exposed player that is playing) | `music_assistant.transfer_queue` with that source named |
| `join` (`other`), `unjoin` | `media_player.join`, `unjoin` |
| `volume`, `mute`, `unmute`, `playback` (play/pause/next/previous/stop) | the shared media actions (see [Structured actions](../README.md#structured-actions)). With the target `here` they go to the speaker's own Music Assistant player first; with a named target they take the generic path below |

For the music capabilities (`play_media`, `now_playing`, `shuffle`, `repeat`, `transfer`, `join`, `unjoin`) the players are the **Music Assistant media players that are exposed to Assist** (registry platform `music_assistant`): a Chromecast that shares a name is never reached. The target is found by name or alias, area, or the speaking device's own room (`here`). Two more fallbacks apply **only when the target is `here`**: a player named like the speaking device (`mark2` on the Mark II), and, for `now_playing`, `shuffle` and `repeat` only, the one player that is playing, paused or buffering. A `transfer` with no source names the one exposed player that is playing (never a player hidden from Assist, whatever Music Assistant lists first). Two candidates, or none: the request goes on as words, as for any structured action.

**Shared controls are not limited to Music Assistant players when the target is named.** `volume`, `mute`, `unmute` and `playback` use a Music Assistant player only for the target `here` (and never the "one that is playing" fallback). For a named target, or when the speaker's room has no Music Assistant player, they go to the generic media path, which resolves **any exposed `media_player`**, including a Chromecast or a TV that shares the name (two with the same name are not guessed: the request goes on as words). This is `async_execute_action()` in `music.py`, and a consequence of "turn the volume up on the kitchen" having no way to say "music".

If the Music Assistant integration's services are missing (not installed, or not loaded), a play request is left to the words; it is not an error. A request shares the hub's 10 second budget with everything else (about 8.5 s here): a search that runs out of time answers "Sorry, Home Assistant took too long to answer." if nothing had started, and "Sorry, I could only do part of that." if playback had already started, never the words on top.

Answers are spoken from this integration's translations (English and French; other languages hear English): "Playing Adam's Song by blink-182 on mark2." A title that no provider has is an answer ("I couldn't find ... in your music"), not a guess.

## Known limits (Home Assistant's Music Assistant integration does not expose them)

- No genre play and no "add the current track to favorites": use the direct or bridge transport of the skill.
- Search is through `music_assistant.search`, which spans your providers; a result that is not in the library is still played if the provider has it. The artist you name narrows the search and rules out a result whose listed artists do not contain it (or are not contained in it: a substring match, so "Muse" can match "Muse Tribute Band"); a result with no artist information, such as a playlist or a station, is not ruled out.
- Favorites are limited to 50 tracks per request.
- Speakers list ("which speakers do I have") is not an action; ask Home Assistant.

Code: `custom_components/thalovant/music.py` (`async_execute_action`, `async_execute_music`, `music_player`, `best_match`), `tests/test_music.py`.

Test vectors: this repository keeps `tests/music_vectors.json` (23 cases, `action` form), which `test_the_shared_vectors` runs. The standalone bridge does **not** read this file: its `tests/test_vectors.py` runs the spec's copy, `[thalovant-connector-spec: thalovant_connector_spec/vectors/music_assistant.json]` (`behavior`, the same 23 case names in `verb`/`args` form, with one extra `request_valid` field). The two were compared by the documentation sweep and agree case for case; nothing in either repository checks that they stay equal (AUDIT.md, SUGGESTIONS.md).
