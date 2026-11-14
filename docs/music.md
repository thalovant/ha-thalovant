Last Edit: Claude Fable 5.2 - 2026-11-13 - Motive: 0.5.0 after the 2026-11-13 recheck: the verb table matches music.py (one verb group per row, `unmute` listed), the volume cap, `targets` not carried, and what tests/music_vectors.json is and is not.

# Music through Home Assistant

If your household runs Music Assistant behind Home Assistant (the *Music Assistant* integration), your Thalovant devices can play and steer it **through the Home Assistant link you already have**: no second connection, no open port, no Music Assistant token on the hub.

```
device -> hub -> thalovant-skill-music-assistant -> thalovant.home.request {action}
       -> hivemind-home-router (your household only) -> this integration (custom_components/thalovant/music.py)
       -> Home Assistant: music_assistant.search / play_media, media_player.* -> Music Assistant
```

## What it does

`MusicRequest` actions are `capability` + `target` (+ `media`, `value`, `other`):

| Capability | Done with |
|---|---|
| `play_media` (`media`: `query`, `type` track/album/artist/playlist/radio, `artist`, `enqueue` play/replace/next/add) | `music_assistant.search` (the best name match across your library and your providers, narrowed by the artist when you name one, never a raw URL), then `music_assistant.play_media` |
| `play_media` with `favorites` | `music_assistant.get_library` (up to 50 favorite tracks), `play_media`, then `media_player.shuffle_set` once playback has started |
| `play_media` with `similar` | `music_assistant.get_queue` (the current track), then `play_media` with radio mode |
| `now_playing` | the player's `media_title` / `media_artist` / state |
| `shuffle`, `repeat` | `media_player.shuffle_set`, `repeat_set` |
| `transfer` (`other` = the source; without it, the one exposed player that is playing) | `music_assistant.transfer_queue` with that source named |
| `join` (`other` = the speaker that joins) | `media_player.join` |
| `unjoin` | `media_player.unjoin` |
| `volume`, `mute`, `unmute`, `playback` (pause/play/next/previous/stop) | the shared media actions (see [Structured actions](../README.md#structured-actions)): `media_player.volume_set`, `volume_mute`, `media_play`, `media_pause`, `media_stop`, `media_next_track`, `media_previous_track` |

These are exactly `MUSIC_CAPABILITIES` and `SHARED_CAPABILITIES` in `custom_components/thalovant/music.py`; a test fails when this table and the code differ (`tests/test_music_contract.py`).

**Volume cap.** The integration's **Highest volume** option (1 to 100, default 100 = no cap) limits every structured `volume` action, absolute or relative, on a Music Assistant player and on any other media player: a request for more is set at the cap and the answer says so ("The volume is at 60 percent, the highest allowed here."). A sentence Assist handles itself is not capped. Code: `actions._volume()`, `actions.max_volume_of()`, `HomeRequestHandler._async_structured()`.

Players are the **Music Assistant media players that are exposed to Assist** (a Chromecast that shares a name is never reached). The target is found by name or alias, area, the speaking device's own room, a player named like the speaking device (`mark2` on the Mark II), and, for "what's playing", shuffle and repeat only, the one player that is playing, paused or buffering (volume, mute and playback never use this fallback: with no player of the speaker's own they go to the generic media path). A `transfer` with no source names the one exposed player that is playing (never a player hidden from Assist, whatever Music Assistant lists first). Two candidates, or none: the request goes on as words, as for any structured action.

Answers are spoken from this integration's translations (English and French; other languages hear English): "Playing Adam's Song by blink-182 on mark2." A title that no provider has is an answer ("I couldn't find ... in your music"), not a guess.

## Known limits (Home Assistant's Music Assistant integration does not expose them)

- No genre play and no "add the current track to favorites": use the direct or bridge transport of the skill.
- Search is through `music_assistant.search`, which spans your providers; a result that is not in the library is still played if the provider has it. The artist you name narrows the search and rules out a result whose listed artists do not contain it (or are not contained in it: a substring match, so "Muse" can match "Muse Tribute Band"); a result with no artist information, such as a playlist or a station, is not ruled out.
- Favorites are limited to 50 tracks per request.
- Speakers list ("which speakers do I have") is not an action here. The connector spec's `music_assistant` connector has a `targets` verb for it since spec 0.4.0; this route does not carry it (`NOT_CARRIED` in `music.py`), so the question goes on as its words.

## Test vectors: what they are

`tests/music_vectors.json` is **this repository's own copy** of the music behaviours, in the shape `world` + `cases` (each case a whole `action` and the expected answer and effects). It is not the connector spec's vector file: that one is organised as `validation` (requests to accept or refuse, which this integration does not replay) and `behavior` (`verb` + `args`), and it has a behaviour this route does not carry (`targets`). The copy is kept by hand and nothing regenerates it. `tests/test_music_contract.py::test_the_private_vectors_still_match_the_specs_behaviours` compares its world and its cases with the spec's `behavior` list, but only where the spec package is installed; this repository's CI does not install it, so there the test is skipped and the two files can drift unseen. On 2026-11-13 the comparison was run against spec 0.4.0: same world, the same 23 cases, the spec has one more (`targets`).

Code: `custom_components/thalovant/music.py` (`async_execute_action`, `async_execute_music`, `music_player`, `best_match`), `tests/test_music.py`, `tests/test_music_contract.py`.
