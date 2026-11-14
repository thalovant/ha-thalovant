Last Edit: Claude Fable 5.2 - 2026-11-13 - Motive: new file: the docs called the structured and music work 0.5.0 while the manifest said 0.4.0; one place now says what each version holds, and a test keeps the version the same in the manifest, here, in QUICK_FACTS.md and in pyproject.toml.

# Changelog

The version Home Assistant and HACS read is `version` in
[`custom_components/thalovant/manifest.json`](custom_components/thalovant/manifest.json).
The first entry below is always that version
(`tests/test_music_contract.py::test_the_version_is_the_same_everywhere`).
Entries before 0.5.0 are summaries of [MAINTENANCE_REPORT.md](MAINTENANCE_REPORT.md)
and of the git history; details and verification are there.

## 0.5.0 (unreleased)

Structured actions and music through the Home Assistant link, and the fixes of the
2026-11-13 recheck. See [README.md](README.md#structured-actions),
[docs/music.md](docs/music.md) and [AUDIT.md](AUDIT.md).

### Added

- **Structured actions**: a hub request can carry an `action` (capability, target,
  value) beside its sentence; it is resolved among the entities exposed to Assist and
  carried out with the entity's own services
  ([`actions.py`](custom_components/thalovant/actions.py), `async_execute()`).
  Options: **Carry out structured requests** (on), **Allow locks, alarms, ...** (off),
  **Alarm code**.
- **Music**: play and steer Music Assistant players (`play_media`, `now_playing`,
  `shuffle`, `repeat`, `transfer`, `join`, `unjoin`, and the shared `volume`, `mute`,
  `unmute`, `playback`) ([`music.py`](custom_components/thalovant/music.py)).
- **Highest volume** option (`max_volume`, 1 to 100, default 100 = no cap): every
  structured volume action is set at most at the cap, and the answer says so when the
  cap lowered what was asked. If that capped call fails, the answer says it failed
  (`action_failed`) and the sentence is not passed to Assist, which would set the level
  that was asked for.

### Changed (recheck of 2026-11-13)

- **A room or floor named alone means its lights**, also when the hub sends it as a
  `name` ("toggle the garage" used to toggle every plug, relay and unclassified cover
  in the room; "toggle downstairs" a whole floor).
- **Covers are sensitive unless they are window coverings.** Opening, toggling or
  positioning a cover needs the sensitive option unless its device class is `awning`,
  `blind`, `curtain`, `shade` or `shutter`. A cover with **no device class** (a usual
  garage door from MQTT, ESPHome or a template) used to open with the option off.
  **If you have such a cover and want it by voice, turn the option on, or give a
  window covering its device class.**
- **A refused sensitive action is answered, not passed on.** With the option off, a
  structured lock, unlock, arm, disarm, siren, valve or cover action is answered with
  a spoken refusal (`error`, `failed_to_handle`). It used to go to Assist as words,
  where an exposed entity could be operated after all. The same holds, with the option
  on, for a sensitive action over several entities and for a disarm without the stored
  alarm code. A sentence the hub sends as plain words (no `action`) is unchanged: it
  goes to Assist.
- **The action is checked against closed lists first**: a known capability, only the
  target keys `name`, `area`, `floor`, `domain`, `here`, and a known domain.
- **`target.all` is removed.** No Thalovant skill sent it, and with a domain it reached
  up to 50 entities. A target that carries it is not an action; its words go to Assist.

### Known limits

- A relay is a `switch` and a script can do anything: neither can be recognised as a
  garage door. Exposed to Assist and named exactly, they are carried out with the
  sensitive option off. Do not expose to Assist what a voice must not operate.
- `tests/music_vectors.json` is this repository's own copy, in an older shape than the
  connector spec's vectors; see [docs/music.md](docs/music.md#test-vectors-what-they-are).

## 0.4.0

Intercom, all off by default: the actions `thalovant.announce`,
`thalovant.cancel_announcement` and `thalovant.list_speakers`, an Intercom notify
entity, and playing the hub's announcements on media players. See
[docs/announcements.md](docs/announcements.md).

## 0.3.0

**Link account**: Home Assistant's own OAuth 2 flow with PKCE through My Home
Assistant is the default sign-in; **Link with a code instead** keeps the device login.

## 0.2.5

The sign-in step says to approve from a phone or computer on the same network as this
Home Assistant.

## 0.2.4

Private (self-hosted) links read the original router source of a routed request.

## 0.2.3

A private link flow for a Christmas Protocol hub run by its operator.
