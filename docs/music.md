Last Edit: Claude Sonnet 5.5 - 2026-11-13 - Motive: Music actions: Music Assistant players played and steered through the Home Assistant link.

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
| `play_media` (`media`: `query`, `type` track/album/artist/playlist/radio, `artist`, `enqueue` play/replace/next/add) | `music_assistant.search` (the best name match in your library, never a raw URL), then `music_assistant.play_media` |
| `play_media` with `favorites` | `music_assistant.get_library` (favorites), `play_media`, then `media_player.shuffle_set` |
| `play_media` with `similar` | `music_assistant.get_queue` (the current track), then `play_media` with radio mode |
| `now_playing` | the player's `media_title` / `media_artist` / state |
| `shuffle`, `repeat` | `media_player.shuffle_set`, `repeat_set` |
| `transfer` (`other` = the source) | `music_assistant.transfer_queue` |
| `join` (`other`), `unjoin` | `media_player.join`, `unjoin` |
| `volume`, `mute`, `playback` (pause/play/next/previous/stop) | the shared media actions (see [Structured actions](../README.md#structured-actions)) |

Players are the **Music Assistant media players that are exposed to Assist** (a Chromecast that shares a name is never reached). The target is found by name or alias, area, the speaking device's own room, a player named like the speaking device (`mark2` on the Mark II), and, for "what's playing", shuffle and repeat only, the one player that is playing. Two candidates, or none: the request goes on as words, as for any structured action.

Answers are spoken from this integration's translations (English and French; other languages hear English): "Playing Adam's Song by blink-182 on mark2." A title that is not in your library is an answer ("I couldn't find ... in your music"), not a guess.

## Known limits (Home Assistant's Music Assistant integration does not expose them)

- No genre play and no "add the current track to favorites": use the direct or bridge transport of the skill.
- Search is through `music_assistant.search`, which spans your providers; a result that is not in the library is still played if the provider has it.
- Speakers list ("which speakers do I have") is not an action; ask Home Assistant.

Code: `custom_components/thalovant/music.py` (`async_execute_action`, `async_execute_music`, `music_player`, `best_match`), shared test vectors `tests/music_vectors.json` (the same file drives the standalone bridge's tests), `tests/test_music.py`.
