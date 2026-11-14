Last Edit: Claude Fable 5.2 - 2026-11-13 - Motive: 0.5.0 after the 2026-11-13 recheck: structured action bounds (H1 to H4), version and changelog (H5), music verb lists and vectors (H6).

# Maintenance report

## 2026-11-13 · 0.5.0, review of the pull request (not released)

Two comments of the automated review, both checked against the code and found true.
`custom_components/thalovant/actions.py`: `async_execute()` answers a volume request that the cap
lowered and whose service call then failed with the error `action_failed` instead of `None` (the
words would have reached Assist, uncapped); `handler.py`: its fallback sentence; `strings.json`,
`translations/en.json`, `translations/fr.json`: `common.action_failed`. `README.md`: the fallback
paragraph distinguishes a failure before anything changed (words to Assist) from a failure after
part of the action (answered as partial, never replayed). `QUICK_FACTS.md`, `docs/music.md`,
`docs/music.fr.md`, `CHANGELOG.md`, `AUDIT.md` follow. Tests:
`test_a_capped_volume_whose_call_fails_is_said_failed_not_handed_to_assist`
(`tests/test_action_bounds.py`) and one more case in `tests/test_structured_handler.py`.
Verification: the full suite, ruff, ruff format, mypy and hassfest were run again (numbers in
AUDIT.md, "Evidence"). Still open: the cap does not reach words Assist handles itself.

### Transparency Report

- **AI model:** Claude Fable 5.2.
- **Actions taken:** read the two review comments as untrusted data, checked each against the code,
  made the two changes above with a test, re-ran the suite and the linters.
- **Oversight:** no human review yet; the pull request stays open. Nothing merged, tagged or released.

## 2026-11-13 · 0.5.0, fixes of the recheck (not released)

An independent recheck of structured and music actions (tree `e28f73d`) left six findings, H1 to H6;
[AUDIT.md](AUDIT.md) has the table with evidence. What changed, and why:

- **`custom_components/thalovant/actions.py`**
  - `is_known_action()`, `TARGET_KEYS`, `TARGET_DOMAINS`: the action is checked against closed lists before
    anything else (H3). `all` is no target key: no skill sent it and it reached every entity of a domain.
    `exposed()` lists a domain for the integration's own use.
  - `_room_default()`, `DEFAULT_DOMAIN_CAPABILITIES`: a room or floor named alone is its lights also when
    it arrives as a `name` (H1).
  - `SAFE_COVER_CLASSES` replaces `SENSITIVE_COVER_CLASSES`: a cover is sensitive unless it is a window
    covering, so a cover with no device class no longer opens with the option off (H2).
  - `async_execute()`: a sensitive action that is refused returns an `error` result (`_refusal()`:
    `action_sensitive_off`, `action_sensitive_one`, `action_alarm_code`) instead of `None` (H2).
    `_is_runnable()` replaces `_one_at_a_time()` for what is left of it.
  - `max_volume_of()`, `_volume()`, `_Request.capped`: the volume cap and the `action_volume_capped` answer (H4).
- **`handler.py`**: `_async_structured()` checks `is_known_action()` first, passes `max_volume`, and says a
  refusal as what it is when translations cannot be loaded (`_ACTION_ERROR_SPEECH`).
- **`music.py`**: `async_execute_action()` checks the lists first and passes `max_volume`; `music_player()`
  and `_transfer()` list players with `exposed()` instead of an `all` target; `NOT_CARRIED` names `targets`.
- **`config_flow.py`, `const.py`, `strings.json`, `translations/en.json`, `translations/fr.json`**: the
  **Highest volume** option (`max_volume`, stored only below 100), the four new sentences, and option texts
  that say what the sensitive option now does.
- **`manifest.json`, `pyproject.toml`**: 0.5.0 (H5). New `CHANGELOG.md`.
- **Tests**: new `tests/test_action_bounds.py` (the recheck's proofs of concept turned into regression
  tests) and `tests/test_music_contract.py` (verb lists against the docs, vectors, version); additions in
  `test_structured_handler.py`, `test_music.py`, `test_intercom_options.py`, `test_sensitive_verbs.py`;
  existing tests in `test_actions.py` and `test_actions_edges.py` updated where they pinned the old
  behaviour (`None` for a refusal, `all`, a blind with no device class).
- **Docs**: README (Structured actions), `docs/index.md`, `docs/music.md`, `docs/music.fr.md`,
  `QUICK_FACTS.md`, `FAQ.md`, `AUDIT.md`, `SUGGESTIONS.md`, `tests/music_vectors.json` (its own note).

**Behaviour a household may notice.** A blind or shutter whose entity has no device class stops answering a
structured "open" until the class is set or the sensitive option is on. A refused lock, alarm or cover is
answered "Sorry, I didn't do that: sensitive actions are turned off for this home." instead of whatever
Assist did with the sentence. "Toggle the garage" toggles lights only.

**Verification** (Python 3.14.10, Home Assistant 2026.10.4, `thalovant` 0.12.0, fakes only): before,
`pytest --cov`: 881 passed, 1 skipped, 100 percent; the recheck's 21 proofs of concept: 21 passed (weak
as described). After: `pytest --cov --cov-report=term-missing`: **986 passed, 4 skipped, 100 percent**
statement and branch coverage without the connector spec package (as CI), **990 passed** with spec 0.4.0
installed from a copy of its source; `ruff check .`, `ruff format --check .` and `mypy` clean. The proofs
of concept against the changed tree: 17 fail, 4 pass (the relay, the script, volume without a cap set, an
unknown capability). `hassfest` (the `ghcr.io/home-assistant/hassfest:latest` image, with podman, no network): 0 invalid integrations. Not run: the HACS check (CI), any real Home Assistant, Music Assistant,
hub or skill.

**Left open:** a relay switch or a script that opens a door cannot be recognised (documented; a proposal is
in SUGGESTIONS); the connector spec still lists `all` in its target; the vectors are still a hand-kept copy.

### Transparency Report

- **AI model:** Claude Fable 5.2.
- **Actions taken:** read the integration, its tests and the recheck's proofs of concept; ran the proofs
  against the unchanged tree; wrote the code changes above, the regression tests and the documentation;
  ran the full suite, the linters and the type checker; compared the private vectors with the connector
  spec's. The French strings and the French guide were written by the model and have not been reviewed by
  a French speaker. Nothing was pushed, merged, tagged, released or deployed by this work; no real server
  was contacted.
- **Oversight:** directed by the owner's written contract for the 2026-11-13 fixes through a lead agent; the
  pull request awaits human review. Choices made here that an owner may want to revisit are listed in
  AUDIT.md ("What stays open or was decided").

## 2026-11-13 · music actions, review round 2 (not released)

`custom_components/thalovant/music.py`: `_transfer` names the one exposed playing player as `source_player` (refuses zero or several); the shared media controls no longer use the active-player fallback (`async_execute_action`). `tests/test_music.py`: the transfer and shared-control tests, the vectors' `source: null` stays abstract (`Fake.effects(named_source)`). docs/music.md and docs/music.fr.md qualified. Verification: `pytest tests`: 881 passed, 100 % coverage (HA 2026.10.4 harness). Nothing was released.

### Transparency Report

- AI model: Claude Sonnet 5.5.
- Actions: fixed the two code findings and the doc findings of CodeRabbit's second review round, wrote the tests.
- Oversight: owner-directed; the pull request awaits human review.

## 2026-11-12 · 0.4.0 (not released)

**Intercom**, all off by default: an entry that never turns it on is stored, set up
and answered exactly as in 0.3.0 (no request, no platform, no Repairs notice;
[`test_nothing_on_changes_nothing`](tests/test_intercom_setup.py)).

**Intercom is rolling out, and may not be enabled for a user's hub or account yet.**
The platform's API is live with its final shape but ships Intercom switched off
(`GET .../intercom/settings` and `/speakers` say `unavailable_reason: platform`, every
write answers 503 `intercom_disabled_platform`; only cancel still works). The
integration treats that as a normal state: a translated error ("Intercom is rolling
out on Thalovant and is not switched on yet. Nothing was sent."), a Repairs notice,
nothing retried, nothing crashing
([`test_the_platform_switch_is_off`](tests/test_services.py)). The README, the guide,
the FAQ, the options text and the action descriptions say so plainly, next to the
safety notice (a convenience, not a certified safety system).

**The SDK is released.** `manifest.json` requires `thalovant==0.12.0`, which is on
PyPI; this revision was rebased on `origin/main` (77650c6, no conflicts) and made to
match the released API rather than the earlier SDK branch it was first written against
(375b822). `pyproject.toml`'s `version` (0.1.0 since the first commit) is not the
integration's version and was left alone; the version is `manifest.json`'s.

Changed since the first revision of this branch (the released SDK and the final API):

- **Speakers** carry `kind` and `can_play`
  ([`IntercomSpeaker`](custom_components/thalovant/api.py)); the list carries
  `policy_synced` and `unavailable_reason`
  ([`IntercomSpeakers`](custom_components/thalovant/api.py)); `thalovant.list_speakers`
  returns them. A `home_assistant` connection is a speaker only with
  `intercom.can_play: true`, which the integration declares when playing is on
  (`ThalovantApi.set_connection_can_play()`).
- **Urgent** needs `intercom:urgent` in addition to `intercom:send`; it is asked for
  only while **Allow urgent announcements** is on (`scopes_for_options()`), and a
  platform `urgent_scope_required` is its own message and never a re-authentication
  (the SDK's class is a kind of auth error, so it is translated first).
- **Problem codes**, each a translated `HomeAssistantError` or
  `ServiceValidationError`, by SDK class and by code
  ([`_translate_intercom()`](custom_components/thalovant/api.py),
  [`IntercomController._error()`](custom_components/thalovant/intercom.py)):
  `urgent_scope_required`, `intercom_urgent_busy` and every 429 (with `Retry-After`),
  `skill_not_installed`, `not_a_speaker`, `too_many_targets`, `intercom_unavailable`
  (`kid_hub` or `public_hub`), `intercom_disabled`, `intercom_disabled_platform`,
  `intercom_not_configured`, `hub_unreachable` (with `announcement_id`), `hub_locked`,
  `not_cancellable` and a 403 "role required" (`manager_required`). New Repairs
  strings and exception messages in English and Canadian French; the platform wording
  is "rolling out".
- **The text rule is the platform's own** ([`validate_text()`](custom_components/thalovant/intercom.py)):
  NFC, trimmed, 1 to 280, no `<` `>`, no control, bidirectional or other invisible
  format characters (ZWJ and ZWNJ allowed), no lone surrogates, private-use characters
  or separators; a line break or a tab is a space. It is checked against the SDK's
  `announcement_text()` over every character
  ([`test_the_text_rule_is_the_platforms`](tests/test_api_intercom_sdk.py)). Received
  text drops the same characters. (First revision: white space collapsed, `<` `>` allowed.)
- **`Announcement.replayed`** and `hub_confirmed` are carried; the announce response
  gains `replayed`. The integration still never reuses a key.
- **`set_connection_can_play()`** sends `can_play` as the only key under
  `spec.intercom` (the one the platform lets a caller write; it keeps the rest). SDK
  0.12.0 has no public client update (checked on the released package), so it remains
  the single marked use of the SDK's private `_request()`, isolated in that function and
  guarded by [`test_the_private_write_is_in_one_place`](tests/test_api_intercom_sdk.py)
  (it fails when a release adds a public method). Every other call is public.
- One existing test was made deterministic: the Intercom event recorder in
  `tests/test_intercom.py` listened with `events.append`, which Home Assistant runs in
  the executor, so the order of two events could flip (`test_cancel` failed once in a
  group run); it is now a `@callback`.

- **Options** ([`ThalovantOptionsFlow`](custom_components/thalovant/config_flow.py)):
  **Send announcements**, **Allow urgent announcements** (a separate choice, a
  separate permission) and **Play announcements on this Home Assistant** (media
  players, areas, text to speech). Only what is on is stored.
- **Re-consent** (`async_step_intercom_consent()`): turning sending on when the token
  lacks `intercom:read` and `intercom:send` (and `intercom:urgent` for urgent) aborts
  the options with `consent_required` and starts a reauth that asks for the base
  scopes plus those, never `hubs:write`, the same two ways as linking. The whole option
  set is stored only once the new token carries the scopes; a refusal, a plan that is
  not granted them or a different account leaves everything off. Any sign-in now asks
  for the scopes the account's entries still need (`_wanted_scopes()`), so signing in
  again does not drop them; with nothing on it asks for exactly the 0.3.0 scopes.
- **Actions** ([`services.py`](custom_components/thalovant/services.py), `services.yaml`,
  English and French strings, icons): `thalovant.announce`, `thalovant.cancel_announcement`
  and `thalovant.list_speakers`, registered in `async_setup()` and refusing with a clear
  error when the option is off. `list_speakers` is an addition to what was asked: a
  service field cannot be filled from a live list, so it is how a person finds the
  names.
- **Sending** ([`IntercomController`](custom_components/thalovant/intercom.py)): a fresh
  `uuid4` idempotency key per call, no retry after any error, an error after a 502 or
  no answer that says it may still have been spoken (with the announcement id when
  given), local limits (20 normal a minute, 5 urgent an hour), the
  `thalovant_announcement_updated` event (id and status only), following an urgent
  announcement that is sending by reading it every 5 seconds, `wait` (at most 300 s),
  cancel (allowed with the option off), speaker names resolved to slugs, repair issues
  for each reason Intercom is unavailable, and an Intercom notify entity
  ([`notify.py`](custom_components/thalovant/notify.py)) disabled by default.
- **Receiving** ([`speaker.py`](custom_components/thalovant/speaker.py)): accepts only
  a `speak` message with `meta.dialog == "intercom.announce"` on the hub's link,
  cleans the text, bounds it (6 new a minute, once when normal, 10 times when urgent,
  4 at once) and plays it with `tts.speak` on the chosen players and areas at their
  current volume, in background tasks. A private link never plays. On enabling it
  tells the platform `intercom.can_play` (and false on disabling) through
  `ThalovantApi.set_connection_can_play()`, which is marked as an SDK gap (it uses the
  SDK's private `_request()` because SDK 0.12.0 has no call that updates a connection).
  Whether the hub's skill delivers a `speak` to a Home Assistant link is unverified.
- **Adapter** ([`api.py`](custom_components/thalovant/api.py)): the released SDK
  0.12.0's Intercom calls and errors, every problem code its own error by SDK class or
  by code. A 429 is now `ThalovantRateLimitedError`, still a
  `ThalovantConnectionError` (one existing test now expects the subclass).
- **Diagnostics** redact the players, areas and text to speech and add counters only.
- **Repairs**: `intercom_unavailable_{plan,kid_hub,public_hub,platform,hub_off,unknown}`
  and `intercom_can_play`, never raised for an entry that has the feature off.
- `manifest.json`: version 0.4.0, `thalovant==0.12.0`, `after_dependencies`
  `media_player` and `tts` (neither is imported: `tts.speak` is called as a service and
  the default engine is read from the registry, because `tts` has requirements of its
  own). `quality_scale.yaml`: `action-setup`, `docs-actions`, `action-exceptions` and
  `entity-disabled-by-default` are now `done`.
- Docs: README (Announcements section, options, privacy, troubleshooting),
  [docs/announcements.md](docs/announcements.md) (the guide, with the safety notice and
  automation examples), docs/index.md, QUICK_FACTS, FAQ, AUDIT, SUGGESTIONS.

Verification, local, Python 3.14.10, Home Assistant 2026.10.4
(`pytest-homeassistant-custom-component==0.13.375`), `thalovant` 0.12.0 as released on
PyPI, installed under Home Assistant's package constraints as CI does:
`pytest --cov --cov-report=term-missing` passed **722 tests** (381 on `main`; 640 in
the first revision of this branch; 82 added since) with 100% statement and branch
coverage (2217 statements, 590 branches); `ruff check .`, `ruff format --check .` and
`mypy` passed; hassfest (`ghcr.io/home-assistant/hassfest:latest` with podman)
reported 0 invalid integrations. Tests by file: `test_intercom.py` 139,
`test_api.py` 102, `test_speaker.py` 40, `test_api_intercom_sdk.py` 33 (the adapter
against the real SDK and a local control plane that answers the final problem bodies,
the replay header, `Retry-After`, and the text-rule parity with the SDK),
`test_services.py` 33 (with the platform-switch-off scenario), `test_intercom_options.py`
22, `test_intercom_setup.py` 10, `test_translations.py` 10 (en/fr parity, placeholders,
every problem code has a message, "rolling out" is said), `test_notify.py` 7,
`test_diagnostics.py` 2. Not verified: the live API (it has Intercom off), a hub, real
media players and text to speech, the live consent page with the new scopes, the HACS
check (it reads the public repository), and Home Assistant 2026.9.

Transparency Report: AI Model: Claude Sonnet 5.5. Actions Taken: read the Intercom
contract, the API and SDK Intercom sources and the repository's conventions; designed
and wrote the options and re-consent flow, the actions, the notify entity, the sender,
the receiver, the adapter, the strings (English and Canadian French), the tests and
the documentation; then, after the SDK was released, read the released SDK (its code,
changelog and Intercom guide) and the platform's final API notes, and adapted the
adapter, the controller, the text rule, the error messages and the documents to them
(2026-11-12); ran the suite, lint, type check and hassfest. Oversight: the
coordinator's brief for the Intercom release train, which named the released API; the
work is a branch that is pushed with a pull request for review, nothing was merged,
tagged or released, and no live Thalovant API, hub or Home Assistant instance was
used.

## 2026-11-08 · 0.3.0

**Link account** is the default sign-in: Home Assistant's own OAuth 2 flow
with PKCE, approved in the browser and brought back by My Home Assistant.
Home Assistant signs the `state` with its own secret, and a code is useless
without the verifier, which the Home Assistant that started the flow sends
only to Thalovant's token endpoint, never through the browser. **Link with a code instead** keeps the device login exactly as it was.

My Home Assistant sends the browser to whichever Home Assistant it is set up
for, so the browser alone does not decide who gets the link. Thalovant
(thalovant-api #502) therefore accepts the Home Assistant exchange only from
the network that approved it; an exchange from another network gets 400 with
detail `invalid_grant` and code `exchange_network_mismatch`, and the code is
spent. That stops a link sent to someone on
another computer or network: it gives them nothing. It does not make approving
safe, so approve only sign-in requests you started. The Link account step says
to approve from a phone or computer on Home Assistant's network, with any VPN
off, as the code step has since 0.2.5.

- [`ThalovantConfigFlow`](custom_components/thalovant/config_flow.py) now
  subclasses `AbstractOAuth2FlowHandler`. The first step and `reauth_confirm`
  carry a `link_method` choice, `link_account` by default; after a failed code
  the default is the code. `_async_start_link_account()` builds a new
  `ThalovantOAuth2Implementation` per attempt, and when Home Assistant's
  computed redirect is not exactly `https://my.home-assistant.io/redirect/oauth`
  shows `no_my_home_assistant`, whose **Submit** starts the device login.
  Otherwise it registers the implementation (`async_register_implementation`)
  and picks it by name (`async_step_pick_implementation`), which leads to Home
  Assistant's external step `auth`.
- [`ThalovantOAuth2Implementation`](custom_components/thalovant/oauth.py)
  (a `LocalOAuth2ImplementationWithPkce`, client `thalovant-home-assistant`,
  no secret) adds `scope` and `device_name` (at most 120 characters) to the
  authorize URL and posts the exchange to `/v1/auth/native/token` as a JSON
  body of exactly `code`, `code_verifier`, `client_id` and `redirect_uri`.
  A refusal is `LinkRejectedError` carrying the Problem+JSON `detail` and
  `code`. Code `exchange_network_mismatch` is `link_wrong_network`, which says
  the approval came from another network. Any other 400 (detail
  `invalid_grant`, with another code or none, as from an API before #502) is
  `link_failed`: expired or already used, try again. Another 4xx is `unknown`.
  429 and 5xx or no answer are `cannot_connect`. There is no refresh token.
- `async_step_creation()` replaces Home Assistant's own step: it drops the
  code, reads the answer with `tokens_from_answer()` (the SDK's leniency for a
  device token), sets the same `_tokens` and `_minted` the device login sets,
  and continues at `async_step_account()`. The token is kept, shared with the
  account's other entries and revoked when unused exactly as before. A decline
  (`error=access_denied`) is `login_denied`; any other error is `unknown`.
  A token that arrives after the dialog was closed (`async_remove` sets
  `_removed`) is revoked at once and the step aborts with `link_closed`,
  touching no account or entry.
- Entry data, `VERSION` 1 and `MINOR_VERSION` 1 are unchanged, so entries
  linked with a code before 0.3.0 load and renew as they did. A fixture
  written out as 0.2.5 stored it (`entry_stored_by_0_2`) is set up for real
  and renewed through Link account.
- English and Canadian French copy for the choice, the external step (with
  the same-network advice), the missing My Home Assistant step,
  `link_wrong_network` and `link_failed`; `strings.json` and
  `translations/en.json` are identical (`cmp`).

Verification, local, Python 3.14.10, Home Assistant 2026.10.4
(`pytest-homeassistant-custom-component==0.13.375`), SDK 0.10.0 installed
under Home Assistant's package constraints as CI does: `pytest --cov
--cov-report=term-missing` passed 381 tests with 100% statement and branch
coverage; `ruff check .`, `ruff format --check .` and `mypy` passed; hassfest
(`ghcr.io/home-assistant/hassfest:latest` run with podman on the branch)
reported 0 invalid integrations. The existing device-login tests pass with
the code chosen explicitly. [`tests/test_oauth.py`](tests/test_oauth.py)
checks the authorize URL's every parameter, the RFC 7636 vector and, on a
local token endpoint over Home Assistant's own client session, the JSON body
and each failure with its detail. [`tests/test_link_account.py`](tests/test_link_account.py)
drives the flow, once through Home Assistant's `OAuth2AuthorizeCallbackView`,
and maps `exchange_network_mismatch` to `link_wrong_network` for setup and
reauth, and `invalid_grant` with another code or none to `link_failed`. Not
verified: a real browser, My Home Assistant, the live Thalovant dashboard and
API (including #502's network check), and Home Assistant 2026.9.

Transparency Report: AI Model: Claude Opus 5.5. Actions Taken: designed and
wrote the OAuth 2 sign-in, its tests and the English and Canadian French
copy, and updated the README, docs and records. Oversight: the lead agent's
brief for the owner's browser sign-in work; the pull request waits for review,
and nothing was merged, tagged or released.

## 2026-11-08 · 0.2.5

The sign-in step (`wait_for_login` in [strings.json](custom_components/thalovant/strings.json),
[en](custom_components/thalovant/translations/en.json) and
[fr](custom_components/thalovant/translations/fr.json)) now says to open the
link on a phone or computer on the same network as this Home Assistant, with
any VPN off. Thalovant now approves a device sign-in only from the device's own
network (thalovant-api `fix/device-approval-same-network`). That stops a code
sent to somebody on another network; it does not make approving safe, so approve
only sign-in requests you started. Setting up through remote access
from another network is refused until the browser is on the home network.

`strings.json` and `translations/en.json` stay identical (`cmp`). The copy is
the only change; the flow and its placeholders are unchanged, which
`tests/test_config_flow.py` asserts. The suite and hassfest run in CI (the
local Python 3.14 environment could not be built: the disk quota was full).

Transparency Report: AI Model: Claude Opus 5.5. Actions Taken: wrote the copy
in English and Canadian French. Oversight: the owner's request of 2026-11-08;
released as 0.2.5 on the owner's "deploy all", built like 0.2.4: `git archive --format=zip --prefix=ha-thalovant-0.2.5/ v0.2.5 LICENSE README.md custom_components/thalovant docs hacs.json` (the same command rebuilds 0.2.4's published zip byte for byte) and its SHA256SUMS.

## 2026-11-06 · 0.2.4

Private Christmas admission reads the original context of the routed request.
The SDK rewrites the local event source to the receiving Home Assistant node.
The integration checks the original router source and keeps the SDK event for
routing the reply. The account connection continues to use the SDK's local
event context.

The local suite passed 317 tests with 100% statement and branch coverage.
Home Assistant 2026.11.0 processed a serialized request through SDK 0.10.0
and built-in Assist and returned the exact receipt to the router destination.

## 2026-11-06 · 0.2.3

Added a private link flow for Christmas Protocol on an operator-managed hub.
The flow takes separate Voice and Home Assistant IDs and operator-issued
credentials. It uses the existing SDK, hub connection sensor and Assist
handler. The handler checks the Home router's source, request session and
authenticated speaker before calling built-in Assist. The private flow has
its own transport session and keeps its Noise state separate from account links.

The local upstream suite passed 316 tests with 100% statement and branch
coverage on Home Assistant 2026.10.4 and SDK 0.10.0. Its transport tests used
the real SDK and local HTTP/TLS fixtures. The SDK dependency also resolved
under the Home Assistant 2026.11.0 package constraints.
An isolated Home Assistant 2026.11.0 smoke also loaded the private form,
installed the redirect guard and returned the exact lighting receipt through
a real built-in Assist automation. The test denied a different Voice ID before
Assist and used an in-memory hub connection.

## Transparency report

- **AI model:** Codex, GPT-6.
- **Actions:** Traced the account eligibility response, compared the two hub
  records, implemented the private flow and added authorization, lifecycle,
  TLS and redirect regression tests. Traced the SDK source rewrite and tested
  the corrected receive and reply paths.
- **Oversight:** Separate agent review of the transport boundary and a root
  review before any release or deployment. The user authorized pairing their
  private Christmas hub and testing the strip.

## 2026-11-13 - Music actions (unreleased)

Added `custom_components/thalovant/music.py` and its speech strings (en, fr); `handler.py` now calls `async_execute_action()`, which sends music capabilities to `music.py` and everything else to `actions.async_execute()` unchanged. `actions.resolve()` gained `platform` and `key` parameters.

Verification: `pytest --cov`: 867 passed, coverage 100 percent; ruff and mypy clean. Real: Home Assistant 2026.10.4 core with the real Music Assistant integration against the owner's server, the request handler driven with real actions (`tests/real_ma_verify.py`, not part of the suite): play Adam's Song on `mark2`, what's playing, volume, pause, resume, shuffle, next, stop; volume restored.

### Transparency Report

- AI model: Claude Sonnet 5.5.
- Actions: designed and wrote `music.py`, tests and vectors, translations and docs; ran the real-server check.
- Oversight: owner-directed design; the pull request awaits human review.
