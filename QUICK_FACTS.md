Last Edit: Claude Sonnet 5.5 - 2026-11-13 - Motive: Music actions through the Home Assistant link (music.py), verified against a real Music Assistant.

# Quick facts

| Fact | Value |
| --- | --- |
| Project | `ha-thalovant` |
| Home Assistant integration domain and version | `thalovant`, `0.4.0` |
| SDK requirement | `thalovant==0.12.0` (released on PyPI; the first with Intercom; `manifest.json`, enforced by `tests/test_api_sdk.py::test_installed_sdk_is_the_manifest_pin`) |
| Config entry points | `ThalovantConfigFlow.async_step_user()`, `async_step_self_hosted()`, `async_step_reauth()` |
| Sign-in methods | Link account (default): `AbstractOAuth2FlowHandler` steps `auth` and `creation` with `ThalovantOAuth2Implementation`; Link with a code instead: `async_step_login()` (device login) |
| OAuth client | `thalovant-home-assistant` (public, PKCE S256, no secret), the device login's registered app |
| Authorize URL | `https://dash.thalovant.com/authorize` |
| Token exchange | `POST https://api.thalovant.com/v1/auth/native/token`, JSON `{code, code_verifier, client_id, redirect_uri}` |
| Redirect | `https://my.home-assistant.io/redirect/oauth` only; without My Home Assistant the flow offers a code (`async_step_no_my_home_assistant()`) |
| Scopes asked | `hubs:read clients:read clients:write` |
| Approval network | Either sign-in completes only when approved from Home Assistant's own network; for Link account, an exchange from another network gets 400 `invalid_grant` with code `exchange_network_mismatch` (error `link_wrong_network`); any other `invalid_grant` is `link_failed` |
| Entry data | Unchanged since 0.2 (`VERSION` 1, `MINOR_VERSION` 1): either sign-in stores the same `tokens` form |
| Runtime entry points | `async_setup()` (registers the actions), `async_setup_entry()`, `async_unload_entry()`, `async_remove_entry()` |
| Private request scope | One authenticated Voice ID and the seven Christmas mirror lighting commands, handled by built-in Assist |
| Private transport | TLS-verified WSS and persistent per-link Noise state |
| Platforms | `binary_sensor` always; `notify` only while **Send announcements** is on |
| Manifest | `dependencies: [conversation]`, `after_dependencies: [media_player, tts]`, `iot_class: cloud_push` |

## Intercom (0.4.0), all off by default

**Intercom is rolling out.** Thalovant ships it switched off for the whole platform: `GET .../intercom/settings` and `/speakers` say `unavailable_reason: platform`, every write answers 503 `intercom_disabled_platform`. It may not be enabled on a user's hub or account yet; the integration reports that clearly (error, Repairs notice), never crashes, never retries.

| Fact | Value |
| --- | --- |
| Options (stored only when on) | `allow_announcements`, `allow_urgent`, `allow_receive`, `speaker_players`, `speaker_areas`, `tts_entity` |
| Extra scopes, asked only when turned on | `intercom:read intercom:send` (announcements), `intercom:urgent` (urgent, only when **Allow urgent announcements** is on; needed in addition to `intercom:send`); never `hubs:write`. A new token also carries `LOGIN_SCOPES` and what other entries need |
| Re-consent | A reauth (`async_step_intercom_consent()`) started by the options flow; options are stored only after the token carries the scopes |
| Actions | `thalovant.announce` (`SupportsResponse.OPTIONAL`), `thalovant.cancel_announcement` (`OPTIONAL`), `thalovant.list_speakers` (`ONLY`), registered in `async_setup()` |
| `announce` fields | `message` (the platform's text rule: NFC, trimmed, 1 to 280, no `<` `>`, control, bidirectional/invisible format (ZWJ/ZWNJ allowed), private-use, surrogate or separator characters; line breaks and tabs become spaces), `target` (`all`, `speakers`, `rooms`, `groups`), `names` (at most 50, each at most 64), `priority` (`normal`, `urgent`), `repeat_times` (1 to 10) with `repeat_interval` (5 to 120 s), `language`, `wait` (at most 300 s), `config_entry_id` |
| Response | `announcement_id`, `status`, `priority`, `deliveries` (`total`, `by_status`), `acked_by`, `replayed`: never the text. `list_speakers`: speakers with `kind` and `can_play`, `rooms`, `groups`, `policy_synced`, `unavailable_reason` |
| Event | `thalovant_announcement_updated` with `announcement_id` and `status` only |
| Notify entity | `notify.<hub>_intercom`, disabled by default, a normal announcement to every speaker |
| Idempotency and retries | A fresh `uuid4` key per call; never reused; no retry after any error |
| Local limits | 20 normal a minute, 5 urgent an hour per entry (the platform's: 20 a minute, 10 an hour per hub, 2 urgent repeating at once per hub) |
| Problem codes mapped (`ThalovantApi._translate_intercom()`, `IntercomController._error()`) | `urgent_scope_required`, `intercom_urgent_busy` (429, `Retry-After`), `skill_not_installed`, `not_a_speaker`, `too_many_targets`, `intercom_unavailable` (`reason` `kid_hub`/`public_hub`), `intercom_disabled`, `intercom_disabled_platform`, `intercom_not_configured`, `hub_unreachable` (with `announcement_id`), `hub_locked`, `not_cancellable`, `plan_limit`, 429, 401/403; a 403 "role required" is `manager_required`; each has a translated message (en, fr) |
| Receive message | `speak` with `data.meta.dialog == "intercom.announce"`, `data.meta.intercom.{id, priority}`, `data.utterance`, `data.lang` |
| Receive limits | 6 new announcements a minute; a normal one played once, an urgent one at most 10 times; 4 plays at once; players unavailable are skipped |
| Playing | `tts.speak` on the chosen players and areas, `cache: false`, language from the message when the engine speaks it, no volume change |
| Platform call for receiving | `PATCH /v1/clients/{id}` with `spec.intercom.can_play` (the one key a caller may write under `spec.intercom`); SDK 0.12.0 has no public client update, so `ThalovantApi.set_connection_can_play()` is the single marked use of the SDK's private `_request()`, tested against the real SDK. A Home Assistant connection is a speaker only with `can_play: true` |
| Repairs | `intercom_unavailable_{plan,kid_hub,public_hub,platform,hub_off,unknown}` (`platform` reads "Intercom is rolling out ... not switched on yet"), `intercom_can_play` |
| Private (self-hosted) links | No Intercom options, no announcing, never play |

Safety: Intercom is a convenience, not a certified safety system. It does not
replace smoke or carbon monoxide alarms, medical alert devices or emergency
services.

Implementation links and tests are indexed in [documentation](docs/index.md) and
[the announcements guide](docs/announcements.md).

## Music (0.5.0, unreleased)

| Fact | Value |
| --- | --- |
| Module | `custom_components/thalovant/music.py`: `async_execute_action()`, `async_execute_music()`, `music_player()`, `best_match()` |
| Capabilities | `play_media`, `now_playing`, `shuffle`, `repeat`, `transfer`, `join`, `unjoin` (plus shared `volume`, `mute`, `playback`) |
| Home Assistant actions used | `music_assistant.search`, `get_library`, `get_queue`, `play_media`, `transfer_queue`; `media_player.shuffle_set`, `repeat_set`, `join`, `unjoin` |
| Players | Music Assistant entities (registry platform `music_assistant`) exposed to Assist |
| Spoken answers | `common.music_*` in `strings.json`, `translations/en.json`, `translations/fr.json` |
| Shared vectors | `tests/music_vectors.json` (also used by thalovant-music-bridge) |
