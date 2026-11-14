Last Edit: Claude Fable 5.2 - 2026-11-13 - Motive: recheck of 2026-11-13 (0.5.0): six findings on structured and music actions with their fixes, tests and what stays open; two earlier rows brought up to the code as it now is.

# Audit

## Intercom (0.4.0)

Intercom is safety-adjacent (a text is spoken aloud in a home, an urgent one can
repeat), so the integration keeps it off by default, in three separate switches
([`ThalovantOptionsFlow.async_step_init()`](custom_components/thalovant/config_flow.py#L942)),
and stores nothing about it until it is on
([`test_options_without_intercom_are_stored_as_before`](tests/test_intercom_options.py#L96),
[`test_nothing_on_changes_nothing`](tests/test_intercom_setup.py#L47): no request, no
platform, no Repairs notice for an entry that never turned it on).

Intercom is also **rolling out on the platform**: Thalovant ships it switched off
(`unavailable_reason: platform`, every write 503 `intercom_disabled_platform`), so it
may not be enabled on a user's hub or account yet. That state is first-class here: a
clear translated error, a Repairs notice, nothing retried, nothing crashing, reads
and cancel still working
([`test_the_platform_switch_is_off`](tests/test_services.py)).

Evidence: local run on Python 3.14.10, Home Assistant 2026.10.4, `thalovant` 0.12.0
as released on PyPI, installed under Home Assistant's package constraints: `pytest
--cov` passed with 100% statement and branch coverage, `ruff check`, `ruff format
--check` and `mypy` are clean, and hassfest (`ghcr.io/home-assistant/hassfest:latest`,
podman) reported 0 invalid integrations. Counts are in
[MAINTENANCE_REPORT.md](MAINTENANCE_REPORT.md).

### What is guaranteed, and where it is tested

- **The text is never logged, stored, evented or put in an error.** It is validated
  by [`validate_text()`](custom_components/thalovant/intercom.py#L140), passed only to
  [`ThalovantApi.announce()`](custom_components/thalovant/api.py#L1006) (which returns an
  [`Announcement`](custom_components/thalovant/api.py) with no text field), and
  every error is a translation key with ids and counts as placeholders
  ([`IntercomController._error()`](custom_components/thalovant/intercom.py#L344)).
  Unknown exceptions are logged by type only
  ([`_unexpected()`](custom_components/thalovant/intercom.py#L427)). Tests assert the
  secret text is absent from the log, the event, the error, its cause, the stats and
  diagnostics:
  [`test_announce`](tests/test_intercom.py#L267),
  [`test_announce_errors`](tests/test_intercom.py#L646),
  [`test_value_error_and_surprises`](tests/test_intercom.py#L778),
  [`test_diagnostics_hold_counts_of_announcements_never_text`](tests/test_diagnostics.py#L80),
  [`test_announce`](tests/test_api_intercom_sdk.py#L249) (real SDK: no text in the
  answer or in any error, for ten kinds of answer).
- **The text rule is the platform's own.** NFC, trimmed, 1 to 280, no `<` `>`, no
  control, bidirectional or other invisible format characters (ZWJ and ZWNJ allowed),
  no lone surrogates, private-use characters or separators; the one difference is
  that a line break or a tab becomes a space here (the SDK refuses them). Checked
  character by character against the SDK's `announcement_text()`
  ([`test_the_text_rule_is_the_platforms`](tests/test_api_intercom_sdk.py)) and by
  [`test_validate_text_refuses`](tests/test_intercom.py).
- **Every problem code the platform can answer is a clear message, and none crashes
  the service.** `urgent_scope_required` (a missing scope, not a dead sign-in: no
  reauth), `intercom_urgent_busy` and any 429 (with `Retry-After`),
  `skill_not_installed`, `not_a_speaker`, `too_many_targets`, `intercom_unavailable`
  (kid or public hub), `intercom_disabled`, `intercom_disabled_platform`,
  `intercom_not_configured`, `hub_unreachable` (with `announcement_id`), `hub_locked`
  and a 403 "role required" are mapped by SDK class **and** by code
  ([`_translate_intercom()`](custom_components/thalovant/api.py),
  [`IntercomController._error()`](custom_components/thalovant/intercom.py)); an
  unknown answer is a `request_refused` with its status and code. Tests:
  [`test_intercom_errors`](tests/test_api.py) (fake SDK, by class and by code),
  [`test_announce_errors`](tests/test_api_intercom_sdk.py) (real SDK and the final
  problem bodies) and [`test_announce_errors`](tests/test_intercom.py).
- **A fresh idempotency key per announcement, and no retry.** The key is
  `str(uuid4())` built inside the one call
  ([`async_announce()`](custom_components/thalovant/intercom.py#L451)); two calls with
  the same words send two keys
  ([`test_every_announcement_has_its_own_key`](tests/test_intercom.py#L302)). Every
  error path leaves exactly one request
  ([`test_announce_errors`](tests/test_intercom.py#L646) and, against the real SDK,
  [`test_announce_errors`](tests/test_api_intercom_sdk.py#L452): the plane saw one
  POST whatever it answered). After a 502 or no answer the error says the
  announcement may still have been spoken, and carries the announcement id when the
  platform gave one.
- **Local rate limits** (20 normal a minute, 5 urgent an hour per entry, below the
  platform's) in [`SlidingWindowLimiter`](custom_components/thalovant/intercom.py#L233):
  [`test_local_rate_limit`](tests/test_intercom.py#L512).
- **Urgent is its own option and its own scope**
  ([`urgent_allowed`](custom_components/thalovant/intercom.py#L312)):
  [`test_urgent_needs_its_option_and_its_scope`](tests/test_intercom.py#L494).
- **Re-consent asks only for the extra scopes, stores nothing until granted, and
  keeps the option off if refused or not granted**
  ([`async_step_intercom_consent()`](custom_components/thalovant/config_flow.py#L220),
  [`_async_finish_consent()`](custom_components/thalovant/config_flow.py#L462)):
  [`test_turning_announcements_on_asks_for_the_permission`](tests/test_intercom_options.py#L223),
  [`test_refused_consent_leaves_everything_off`](tests/test_intercom_options.py#L305),
  [`test_a_plan_without_intercom_is_not_granted_the_scope`](tests/test_intercom_options.py#L332),
  [`test_consent_with_another_account`](tests/test_intercom_options.py#L352) (the new
  token is revoked). With nothing on, a sign-in asks for exactly the 0.3.0 scopes
  ([`test_sign_ins_with_nothing_on_ask_for_what_they_always_did`](tests/test_intercom_options.py#L507)).
- **Receiving admits one message shape and bounds it**
  ([`parse_announcement()`](custom_components/thalovant/speaker.py#L82),
  [`IntercomSpeakerHandler._admit()`](custom_components/thalovant/speaker.py#L184)):
  6 new announcements a minute, a normal one once, an urgent one at most 10 times, 4
  plays at once ([`test_per_minute_limit`](tests/test_speaker.py#L254),
  [`test_repeats_of_an_urgent_announcement`](tests/test_speaker.py#L264),
  [`test_too_many_plays_at_once`](tests/test_speaker.py#L512),
  [`test_invalid_announcements_are_ignored`](tests/test_speaker.py#L244)); control,
  bidirectional and angle-bracket characters are removed
  ([`clean_received_text()`](custom_components/thalovant/intercom.py#L166),
  [`test_the_text_is_cleaned`](tests/test_speaker.py#L148)); no volume is touched
  ([`test_urgent_does_not_touch_the_volume`](tests/test_speaker.py#L138)); the loop is
  never blocked ([`test_it_never_blocks_the_loop`](tests/test_speaker.py#L154)); a
  private link never plays
  ([`test_a_private_link_never_plays`](tests/test_speaker.py#L552)).
- **Cancel is not gated by the option**
  ([`async_cancel()`](custom_components/thalovant/intercom.py#L572)):
  [`test_cancel_works_with_announcements_off`](tests/test_intercom.py#L974).

### Known limits and findings

1. **Not run against a live API, hub or media player, and the platform has Intercom
   switched off.** The released API ships it dark
   (`[thalovant-api: docs/intercom.md]`, "Platform switch"), so nothing here has
   spoken through a real hub. The adapter is tested against the real, released SDK
   and a local control plane that answers the final shapes (speaker `kind`,
   `can_play`, `policy_synced`; `Idempotency-Replayed`; the problem codes with their
   `Retry-After`, `announcement_id`, `reason`, `announcement_status`). Not verified:
   the live consent page with the new scopes, the platform's live answers, a hub
   delivering `speak` to this connection, real text to speech and media players, and
   Home Assistant 2026.9 (the suite ran on 2026.10.4).
2. **Receiving is not proven end to end.** The platform now takes
   `spec.intercom.can_play` from a caller on a connection (the one key it allows;
   `carry_platform_owned_client_keys` keeps the rest), and a Home Assistant connection
   is a speaker only with `can_play: true`: this integration declares it. What is
   unverified is the hub side: whether the Intercom skill addresses a `speak` message
   of the shape `parse_announcement()` accepts to a Home Assistant link (the skill
   learns a speaker's peer from the messages it hears; Home Assistant sends none of
   the kind). See [SUGGESTIONS.md](SUGGESTIONS.md).
3. **SDK gap.** SDK 0.12.0 has no public call that updates a connection (checked on
   the released package), so
   [`ThalovantApi.set_connection_can_play()`](custom_components/thalovant/api.py#L1057)
   reads it with the public `get_client()` and writes the whole spec back with the
   SDK's private `_request()` (`If-Match`, one retry on 412), with `can_play` as the
   only key under `spec.intercom` (the one the platform lets a caller write). It is
   the only private use, isolated in that one function
   ([`test_the_private_write_is_in_one_place`](tests/test_api_intercom_sdk.py) fails
   when a release adds a public method, or a second private use appears). A private
   call can break in any SDK release; the real-SDK test
   ([`test_can_play`](tests/test_api_intercom_sdk.py#L517)) would catch it. Every
   other call (announce, cancel, get, list, settings, speakers) is the SDK's public
   API.
4. **`intercom:urgent` is in the final API.** An urgent announcement needs it in
   addition to `intercom:send`; the registered app may ask for it by name
   (Link account and the device flow); Free plans cannot mint it. It is asked for
   only when **Allow urgent announcements** is on
   ([`scopes_for_options()`](custom_components/thalovant/intercom.py)); without it the
   platform answers `urgent_scope_required` before spending anything, which is a
   message, not a re-authentication. A plan that is not granted it leaves the
   option off (fails closed).
5. **The re-consent replaces the account's token for every entry.** Signing in again
   revokes the previous token, so the new one carries the base scopes plus every
   Intercom scope an entry's options need
   ([`_wanted_scopes()`](custom_components/thalovant/config_flow.py#L871),
   [`test_new_sign_ins_ask_for_what_stays_on`](tests/test_intercom_options.py#L476)).
   With two Thalovant accounts, linking one asks for the other's Intercom scopes too,
   which its plan may not grant. Known, not handled.
6. **Receiving trusts the hub link.** Like the existing request handler for account
   links, it checks the message, not its `context.source`; only the hub's
   authenticated connection can deliver it. A compromised hub could make this Home
   Assistant speak up to 6 new announcements a minute on the chosen players. The
   hub's `speak` messages carry no signature the integration can check.
7. **What the media player and the text to speech do is outside.** `tts.speak` plays
   as an announcement (a player that does not support that may interrupt what it is
   playing), at the player's volume (a muted or very quiet player may not be heard),
   and an engine may log or cache audio despite `cache: False`
   ([`_async_play()`](custom_components/thalovant/speaker.py#L279)).
8. **Home Assistant keeps what an automation was told to say** (traces, the
   automation's YAML, the `call_service` event on the bus). The integration cannot
   prevent that; the docs say so.
9. **Counters are in memory.** The local rate limits and the receive limits restart
   with the entry. The platform's own limits still apply to announcements.
10. **Following is polling.** An urgent announcement that is sending is read every 5
    seconds for as long as it can last
    ([`_async_follow()`](custom_components/thalovant/intercom.py#L542)); the platform
    emits a stream event the integration does not consume. `wait` holds a service call
    for 300 seconds at most.
11. **Names are typed.** A service field cannot be filled from a live list, so
    `names` is free text, checked by the platform; `thalovant.list_speakers` shows the
    valid ones. A speaker named by its display name is resolved to its slug
    ([`_async_resolve()`](custom_components/thalovant/intercom.py#L619)); two speakers
    with one name are refused.
12. **The "role required" refusal is recognised by its sentence.** A plain tenant
    member's 403 has no code ("Manager role required for this tenant resource
    change"), so `manager_required` is chosen when a 403's detail says "role
    required". If the sentence changes, the person gets the generic `request_refused`
    with HTTP 403: still a clear refusal, never a crash.
13. **`policy_synced: false` is informational.** The platform says a consent change
    may take a moment to reach the hub; `thalovant.list_speakers` passes it on, and
    nothing else is gated by it.
14. **Household-typed labels** (speaker names, rooms, groups, `acked_by`) are made
    safe before the action returns them
    ([`sanitize_label()`](custom_components/thalovant/intercom.py#L216),
    [`test_list_speakers`](tests/test_services.py)): control characters removed and 80
    characters at most, so a name cannot carry instructions into an automation or a
    language model that reads the response.

## Link account (0.3.0)

Link account
([`ThalovantConfigFlow._async_start_link_account()`](custom_components/thalovant/config_flow.py#L772),
[`ThalovantOAuth2Implementation`](custom_components/thalovant/oauth.py)) uses Home Assistant's own OAuth 2
machinery. The `state` is a JWT signed with this installation's secret, and
Home Assistant's `OAuth2AuthorizeCallbackView` refuses any other with a 400
and leaves the flow waiting
([`test_link_account_through_the_callback_view`](tests/test_link_account.py#L205)).
The exchange sends the PKCE verifier, whose S256 challenge went out in the
authorize URL ([`test_link_account`](tests/test_link_account.py#L138) checks the pair). The
verifier goes only to Thalovant's token endpoint, in the exchange's JSON body
and never through the browser, and each attempt makes a new one
([`test_each_link_has_its_own_verifier`](tests/test_oauth.py#L153),
[`test_link_account_invalid_grant`](tests/test_link_account.py#L259)). The redirect must be
exactly My Home Assistant's
([`through_my_home_assistant`](custom_components/thalovant/oauth.py#L87)); otherwise the flow offers
the device login instead
([`test_without_my_home_assistant_a_code_is_offered`](tests/test_link_account.py#L355),
[`test_own_address_is_not_enough`](tests/test_link_account.py#L379)).

Finding (API review, 2026-11-08): My Home Assistant forwards the code to
whichever Home Assistant the approving browser is set up for. A signed state
and PKCE only mean that the Home Assistant that started the flow is the one
that can use the code. If somebody sends you their link and you approve it,
the code can reach their Home Assistant, which holds the verifier. Neither
method makes approving somebody else's request safe. Mitigation:
thalovant-api #502 accepts the Home Assistant exchange only from the network
that approved it; from another network it answers 400 with detail
`invalid_grant` and code `exchange_network_mismatch`, and spends the code. A link sent to someone on another computer or network gives
them nothing. The copy says to approve from a phone or computer on Home
Assistant's network, and to approve only requests you started.
Only that code maps to `link_wrong_network`
([`config_flow.py`](custom_components/thalovant/config_flow.py#L232),
[`test_link_account_invalid_grant`](tests/test_link_account.py#L259),
[`test_reauth_link_failure_returns_to_confirm`](tests/test_link_account.py#L484)). Any
other `invalid_grant`, including one with no code from an API before #502, is
`link_failed` (expired or already used), so the flow never names a network it
was not told about. The detail and code are read by
[`_problem()`](custom_components/thalovant/oauth.py#L161). The network check
itself is the API's and is not tested here.

Secrets: the exchange posts JSON
([`oauth.py`](custom_components/thalovant/oauth.py#L116),
[`test_exchange_posts_json`](tests/test_oauth.py#L190) on a local endpoint).
No error message carries the code or the verifier
([`test_exchange_errors`](tests/test_oauth.py#L253)). A refused code logs the HTTP
status and the problem's detail and code only. `async_step_creation()`
drops the code before the exchange
([`config_flow.py`](custom_components/thalovant/config_flow.py#L215)). It also replaces Home Assistant's own
creation step, which would log a token without `expires_in` in full and store
it as an OAuth entry. The token is held like a device login's: `_tokens` and
`_minted` ([`config_flow.py`](custom_components/thalovant/config_flow.py#L254)), revoked when unused
([`test_link_account_no_hubs_revokes_the_token`](tests/test_link_account.py#L401)).

Fixed in review (CodeRabbit on #26): closing the dialog while the exchange
was in flight let the token arrive after `async_remove` had run, so nothing
revoked it. `async_step_creation()` now revokes such a token and aborts
([`config_flow.py`](custom_components/thalovant/config_flow.py#L247),
[`test_closed_while_thalovant_answers`](tests/test_link_account.py#L544)). The same window
exists, from before 0.3.0, for a connection whose creation is in flight when
the dialog closes; it is left as it was.

Known, accepted: the last implementation registered stays in Home Assistant's
implementation registry (`hass.data`) after its flow ends, with its verifier.
The verifier holds no token. It is worthless once its code is spent or past
its 60 seconds, and the next attempt replaces it. There is no public way to
unregister an implementation.

Not verified locally: the Home Assistant frontend opening the tab, My Home
Assistant's redirect, the live dashboard consent page (including how it reads
`scope`, sent as `hubs:read+clients:read+clients:write`, and a `state` of about
200 characters) and the live token endpoint, with #502's network check. The
minimum Home Assistant 2026.9 was not run; the suite ran on 2026.10.4.

## Earlier findings

The account sign-in flow obtains its hub list from the Thalovant control plane.
That list cannot enroll an operator-managed hub with no control-plane record.
[`ThalovantConfigFlow.async_step_self_hosted()`](custom_components/thalovant/config_flow.py)
provides a separate configuration entry with no account token. Renewal keeps
the selected hub and Voice ID. The hub operator revokes its client when the
link is removed. [Config and lifecycle tests](tests/test_self_hosted.py).

The private handler validates the exact router source, correlated session,
authenticated Voice ID and lighting phrase before Assist. It uses the built-in
agent for the bounded request set. The transport pins the selected WSS endpoint,
checks TLS, rejects redirects and uses the SDK's persistent Noise identity.
[Request boundary](custom_components/thalovant/self_hosted.py),
[transport regressions](tests/test_self_hosted_transport.py).

Version 0.2.3 dropped routed requests because the SDK's local event identifies
the receiving node as the source. The same serialized request produces no reply
on 0.2.3 and an exact Assist receipt on 0.2.4. The fixed integration checks the
original context from the authenticated connection and denies events with a
forged source or missing original context. The SDK retains the router
destination and correlated session on the reply.
[Routed request regression](tests/test_self_hosted_transport.py).

Local validation passed 317 tests with 100% statement and branch coverage.
The Home Assistant 2026.11.0 smoke used actual SDK receive and reply framing,
the device registry and built-in Assist with an in-memory transport.
Live hub admission, the physical mirror and restoration are separate acceptance
checks for the deployment.


## Security review of structured actions (2026-11-13)

Evidence: `pytest` 833 passed, `ruff`, `ruff format --check` and `mypy` clean on Home Assistant
2026.10.4; each fix below has a test that fails without it.

| Severity | Finding | Where | State |
| --- | --- | --- | --- |
| High | The alarm code was in diagnostics: `entry.options` is dumped and `alarm_code` was not in `TO_REDACT`, so a diagnostics file pasted into a public issue carried the code that disarms the panel. | [`diagnostics.py`](custom_components/thalovant/diagnostics.py) `TO_REDACT`; [`test_diagnostics_never_hold_the_alarm_code`](tests/test_diagnostics.py) | Fixed |
| Medium | "Unlock the kitchen", `{"all": true, "domain": "lock"}` or a floor name resolved to every lock in it once sensitive actions were on; `activate` with `all` ran every exposed script, `power_off` with `all` switched off every exposed automation (up to `MAX_TARGETS` = 50). A hub, router or future skill bug could ask for it. | [`actions.py`](custom_components/thalovant/actions.py) `async_execute` (`action_sensitive_one`), `_is_runnable`; [`test_a_sensitive_action_never_spreads_over_a_room_or_a_floor`](tests/test_actions.py), [`test_scripts_and_automations_are_run_or_switched_one_at_a_time`](tests/test_actions.py) | Fixed. Since the recheck below: a sensitive spread is refused aloud instead of going to Assist, and `all` is no target at all |
| Medium | A window cover opened without the sensitive switch (only garage, gate and door classes were gated). | `SAFE_COVER_CLASSES` (the list was inverted by the recheck below: sensitive unless a window covering); [`test_opening_a_window_cover_is_sensitive`](tests/test_actions.py) | Fixed |
| Low | No replay or age check on a request: `HomeRequestHandler.async_answer` answers any `thalovant.home.request` it is handed. The Noise session already refuses replay, tampering and reordering on the wire, so only the hub itself could replay one. A `request_id` cache of the last 256 ids would close it. | [`handler.py`](custom_components/thalovant/handler.py) `async_answer` | Open, see SUGGESTIONS |
| Low | Only the self-hosted path checks that a request came from `thalovant.home.router` and that the session is `home-<request_id>`; the normal path trusts the link. | [`self_hosted.py`](custom_components/thalovant/self_hosted.py) `permits_lighting_request` | Open |
| Low | The normal link runs on Home Assistant's shared aiohttp session, which follows redirects on the SDK's `ws_connect` (measured with aiohttp 3.14.5: a 307 from the upgrade URL is followed). TLS is verified (`ssl=True`, certifi/system store) and the Noise key pin makes a redirected hub fail with `ThalovantHubKeyChangedError`, so no credential is given away, but the self-hosted path rejects redirects explicitly and this one does not. | [`__init__.py`](custom_components/thalovant/__init__.py) `async_setup_entry` (`async_get_clientsession`), `thalovant._hive._WSSCarrier.open` | Open |
| Low | The alarm code is stored in clear in the config entry options (Home Assistant's own `.storage/core.config_entries`, as every integration's secrets are) and travels in the `alarm_control_panel` service data, which Home Assistant fires on its event bus to administrators. | `ThalovantOptionsFlow`, `_arm` and `_disarm` in `actions.py` | Accepted, documented |
| Low | A voice-only disarm: anyone the speaker hears can ask for what the skill builds. The 0.5.0 skill never builds `disarm`, `unlock` or `arm`; the router would carry one. | `ACTION_CAPABILITIES` in hivemind-home-router | Owner decision before any skill builds it |

Checked and found sound: services are called only from the closed `BUILDERS` set with data built
from validated fields (no entity id, service or domain comes from the hub); only entities exposed
to Assist are resolved (`async_should_expose`); two entities or two areas with one name resolve to
nothing; a failure after part of an action is reported as partial and never retried as words
(`test_a_failure_after_part_of_it_is_done_is_reported_not_retried`); the logs carry request ids and
exception type names only; the announcement receiver is off by default, closed and rate limited.

## Recheck of structured and music actions (2026-11-13, 0.5.0)

An independent recheck ran proofs of concept against the tree at `e28f73d` (structured actions and
music as merged, manifest 0.4.0) on Home Assistant 2026.10.4. Each finding below was reproduced here
first, then fixed with a test that asserts the fixed behaviour.

### Evidence (run on 2026-11-13, Python 3.14.10, Home Assistant 2026.10.4, `thalovant` 0.12.0)

| Check | Result |
| --- | --- |
| The recheck's 21 proof-of-concept tests against the unchanged tree | 21 passed: every weakness present as described |
| `pytest --cov --cov-report=term-missing` before any change | 881 passed, 1 skipped, coverage 100 percent (statements and branches) |
| The same after the change, as this repository's CI installs it (no connector spec package) | **986 passed, 4 skipped**, coverage 100 percent. The 4 skipped are the comparisons with the spec ([`tests/test_sensitive_verbs.py`](tests/test_sensitive_verbs.py), [`tests/test_music_contract.py`](tests/test_music_contract.py)) |
| The same with the connector spec 0.4.0 installed from a copy of its source | **990 passed**, none skipped, coverage 100 percent |
| The recheck's proofs of concept against the changed tree | 17 fail, 4 pass. Failing: the 3 room and floor cases, the 3 unclassified-cover cases, and 11 "holds" cases that asserted `None` (left to Assist) where the answer is now a refusal or, for the room, its lights. Still passing: the relay switch and the script (H2, open below), volume 100 with no cap set (the cap is an option, default 100), and an unknown capability |
| `ruff check .`, `ruff format --check .`, `mypy` (strict) | clean |
| Mutation check of the verb-list test | adding a verb to `SHARED_CAPABILITIES`, or removing one from the QUICK_FACTS row, makes `test_the_docs_list_exactly_the_verbs_the_code_carries` fail |
| Not run here | `hassfest` and the HACS check (CI only); a real Home Assistant, a real Music Assistant, a hub or a skill (fakes only) |

### Findings

| ID | Severity | Finding | Fix | Test | State |
| --- | --- | --- | --- | --- | --- |
| H1 | Medium | "Toggle the garage": a name that is no entity's is read as an area or floor, but the lights-only default applied only to `target.area`. A bare name toggled every exposed light, switch, fan, helper and cover of the room (the freezer plug, the door relay, the door); "toggle downstairs" a whole floor, up to 50 entities | [`_room_default()`](custom_components/thalovant/actions.py) (line 333) applies `DEFAULT_DOMAINS` to `power_on`, `power_off`, `toggle` with no `domain` in every branch of [`resolve()`](custom_components/thalovant/actions.py): `area`, `floor`, `here`, and a name that is an area or a floor | [`test_toggle_the_garage_toggles_its_lights_and_nothing_else`](tests/test_action_bounds.py), [`test_a_floor_name_means_the_floors_lights`](tests/test_action_bounds.py), [`test_power_off_with_a_room_as_name_leaves_heating_plugs_and_players_alone`](tests/test_action_bounds.py), [`test_a_room_as_name_and_a_room_as_area_mean_the_same`](tests/test_action_bounds.py); not narrowed where it must not be: [`test_a_domain_named_with_the_room_is_still_honoured`](tests/test_action_bounds.py), [`test_a_capability_that_names_its_own_domain_is_not_narrowed_to_lights`](tests/test_action_bounds.py) | Fixed |
| H2a | Medium | A garage door was known only by `device_class` in `garage`, `gate`, `door`, `window`. A cover with **no** device class opened, toggled and was positioned with sensitive actions off | [`SAFE_COVER_CLASSES`](custom_components/thalovant/actions.py) (line 192) and [`_is_sensitive()`](custom_components/thalovant/actions.py) (line 445): a cover is sensitive to open, toggle or position unless its class is `awning`, `blind`, `curtain`, `shade` or `shutter`. `damper` and any class Home Assistant adds later are sensitive until listed | [`test_a_garage_door_with_no_device_class_does_not_open_with_sensitive_off`](tests/test_action_bounds.py), [`test_closing_any_cover_and_moving_a_window_covering_are_not_sensitive`](tests/test_action_bounds.py), [`test_the_safe_cover_classes_are_real_ones_and_never_a_way_in`](tests/test_action_bounds.py), [`test_what_is_sensitive`](tests/test_actions_edges.py) | Fixed. Behaviour change: an unclassified blind now needs its device class or the option |
| H2b | Medium | A structured action refused as sensitive returned `None`, and [`_async_structured()`](custom_components/thalovant/handler.py) then let the sentence go to Assist, which could operate the exposed entity after all | [`async_execute()`](custom_components/thalovant/actions.py) (lines 786 to 814) returns a refusal ([`_refusal()`](custom_components/thalovant/actions.py)): `action_sensitive_off` for a flagged verb (before anything is resolved) or a sensitive entity with the option off; `action_sensitive_one` for several sensitive entities with it on; `action_alarm_code` for a disarm without the stored code. The handler answers it as `error` with `failed_to_handle` and the sentence (the one error the hub's skills speak and never retry in words); [`_ACTION_ERROR_SPEECH`](custom_components/thalovant/handler.py) keeps the sentence right when translations cannot be loaded | [`test_a_sensitive_action_that_is_refused_never_reaches_assist_as_words`](tests/test_structured_handler.py), [`test_the_refusal_is_said_in_the_request_language`](tests/test_structured_handler.py), [`test_with_sensitive_on_it_is_done_and_a_disarm_without_the_code_is_refused`](tests/test_structured_handler.py), [`test_a_refusal_whose_sentence_cannot_be_made_is_still_said_as_what_it_is`](tests/test_structured_handler.py), [`test_a_sensitive_action_is_refused_aloud_when_sensitive_is_off`](tests/test_action_bounds.py), [`test_a_sensitive_verb_is_refused_aloud_unless_the_household_opted_in`](tests/test_sensitive_verbs.py) | Fixed |
| H2c | Medium | A relay `switch` that opens a garage door, and a `script` that does, are carried out with sensitive actions off | Not classifiable from the entity: a switch has no device class that says "door", a script can do anything. H1 keeps both out of a room or floor request; an entity not exposed to Assist is never reached | [`test_known_limit_a_relay_or_a_script_named_exactly_is_carried_out`](tests/test_action_bounds.py) pins the limit | **Open**, documented (README, FAQ); a household-marked list is proposed in [SUGGESTIONS.md](SUGGESTIONS.md) |
| H3 | Medium | `target.all` with a domain reached up to 50 entities and no skill sent it. The capability and the target were not checked against closed lists before use: an unhashable capability raised, any string was accepted as a domain for a state read | `all` is removed: [`TARGET_KEYS`](custom_components/thalovant/actions.py) (line 121). [`is_known_action()`](custom_components/thalovant/actions.py) (line 218) checks capability, target keys and domain ([`TARGET_DOMAINS`](custom_components/thalovant/actions.py), 30 domains) first, in [`_async_structured()`](custom_components/thalovant/handler.py) (line 394) before anything is read or created, and again in [`async_execute_action()`](custom_components/thalovant/music.py), [`async_execute()`](custom_components/thalovant/actions.py) and [`resolve()`](custom_components/thalovant/actions.py). The integration's own "every Music Assistant player" uses [`exposed()`](custom_components/thalovant/actions.py), which no request can reach | [`test_an_action_outside_the_closed_lists_is_not_an_action`](tests/test_action_bounds.py) (19 cases), [`test_an_action_inside_the_lists_is_known`](tests/test_action_bounds.py), [`test_everything_exposed_is_listed_only_from_inside`](tests/test_action_bounds.py), [`test_an_action_outside_the_closed_lists_is_only_its_words`](tests/test_structured_handler.py), [`test_every_domain_a_capability_acts_on_is_a_target_domain`](tests/test_sensitive_verbs.py); with the spec installed [`test_the_target_domains_are_exactly_the_specs`](tests/test_sensitive_verbs.py) | Fixed. The connector spec (0.4.0) still lists `all` in the target: see SUGGESTIONS |
| H4 | Low | A volume of 100, absolute or by a step of 100, was carried out with no bound a household could set | Option `max_volume` ([`CONF_MAX_VOLUME`](custom_components/thalovant/const.py), [`ThalovantOptionsFlow.async_step_init()`](custom_components/thalovant/config_flow.py)), read with [`max_volume_of()`](custom_components/thalovant/actions.py) and applied in [`_volume()`](custom_components/thalovant/actions.py) (line 637); the answer is `action_volume_capped` with the level when the cap lowered what was asked | [`test_a_volume_above_the_cap_is_set_at_the_cap_and_said_so`](tests/test_action_bounds.py) (10 cases), [`test_without_a_cap_a_volume_of_100_is_carried_out`](tests/test_action_bounds.py), [`test_the_cap_an_option_value_means`](tests/test_action_bounds.py), [`test_the_volume_cap_holds_on_the_speakers_own_music_player`](tests/test_music.py), [`test_the_volume_cap_option_holds_and_the_answer_says_the_level`](tests/test_structured_handler.py), [`test_the_volume_cap_is_stored_only_when_it_is_one`](tests/test_intercom_options.py), [`test_a_volume_cap_outside_1_to_100_is_not_accepted`](tests/test_intercom_options.py) | Fixed for structured actions. A sentence Assist handles itself is not capped (not this integration's path) |
| H5 | Low | `manifest.json` said 0.4.0 while the docs called this work 0.5.0; there was no changelog | Manifest and `pyproject.toml` 0.5.0, new [CHANGELOG.md](CHANGELOG.md), QUICK_FACTS and docs brought in line | [`test_the_version_is_the_same_everywhere`](tests/test_music_contract.py) | Fixed |
| H6 | Low | [`tests/music_vectors.json`](tests/music_vectors.json) called itself "the same file" as the bridge's and the docs called it shared, but it is a private copy in the shape `cases`, while the connector spec's vectors are `validation` and `behavior`. Nothing tied the verb list in `music.py` to what the docs claim (the docs omitted `unmute`) | The file's own note, [docs/music.md](docs/music.md), [docs/music.fr.md](docs/music.fr.md) and QUICK_FACTS say what it is and that the comparison with the spec runs only where the spec is installed. [`NOT_CARRIED`](custom_components/thalovant/music.py) names `targets`. The docs list the verbs as the code has them | [`test_the_docs_list_exactly_the_verbs_the_code_carries`](tests/test_music_contract.py), [`test_every_music_verb_has_its_runner_and_every_shared_one_its_builder`](tests/test_music_contract.py), [`test_the_private_vectors_have_the_shape_the_docs_say`](tests/test_music_contract.py); with the spec installed [`test_the_route_carries_the_specs_music_verbs_except_the_ones_it_names`](tests/test_music_contract.py), [`test_the_private_vectors_still_match_the_specs_behaviours`](tests/test_music_contract.py) | Fixed as documentation and a guard; the copy itself is still kept by hand (see SUGGESTIONS) |

Severity: H1 and H2 as the recheck rated them; H3 to H6 were not rated by it and are rated here.

### What stays open or was decided

- **Relays and scripts (H2c)** cannot be recognised; see above.
- **With sensitive actions on**, a sensitive action that names nothing the integration can find, or whose
  service is missing or fails before anything changed, still goes on as words, like any other action
  ([`async_execute()`](custom_components/thalovant/actions.py), the two `return None` after the refusals). The household opted in; Assist then
  asks or answers.
- **Plain words are not governed by the sensitive option.** A request with no `action` goes to Assist as
  before; Home Assistant's exposure rules decide there. The option's text now says so.
- **Several runnable entities** (scripts, automations, scenes, buttons) in one room still return `None`
  (words), not a refusal: they are not sensitive ([`_is_runnable()`](custom_components/thalovant/actions.py)).
- **`damper`** is treated as sensitive (it is not a window covering); an owner decision could move it.
- **Technical debt:** `MAX_TARGETS` stays 50 for a room or a floor; the cap answer says the level only
  when the cap lowered it (a plain volume action still answers "Done.").

## Music actions (unreleased)

- [`music_player()`](custom_components/thalovant/music.py) never reaches a player that is not a Music Assistant entity or not exposed to Assist ([`test_a_chromecast_with_the_same_name_is_not_a_music_player`](tests/test_music.py), [`test_an_unexposed_player_is_never_reached`](tests/test_music.py)).
- No raw URL is ever played: media is a name searched in Music Assistant ([`best_match()`](custom_components/thalovant/music.py)).
- A failure after music started answers "partial" and never repeats the sentence through Assist ([`test_a_failure_after_the_music_started_keeps_what_was_done`](tests/test_music.py)).
- Known limit: name matching is a 0.6 similarity threshold (`MIN_MATCH`); a very different title spelling is "not found".
- **Fixed (review round 2): a transfer with no source took any playing queue.** `_transfer` sent no `source_player`, so Home Assistant's Music Assistant integration took the first playing queue of the whole server, exposed to Assist or not. It now names the one exposed player that is playing, and does not guess between two or none ([`test_a_transfer_without_a_source_names_the_one_exposed_player_that_is_playing`](tests/test_music.py), [`test_a_transfer_without_a_source_does_not_guess_between_two_or_none`](tests/test_music.py)).
- **Fixed (review round 2): a shared control borrowed another room's player.** Volume, mute and playback used the "the one active player" fallback, so a speaker whose room has a Chromecast and no Music Assistant player changed the player in another room. The fallback now serves `now_playing`, `shuffle` and `repeat` only ([`test_a_shared_control_never_borrows_another_rooms_playing_player`](tests/test_music.py)).
- **Documented (review round 2): artist matching is a substring match** and a result without artist information is not ruled out ([`best_match()`](custom_components/thalovant/music.py); docs/music.md, docs/music.fr.md).
- **Recheck (0.5.0): the verb lists and the vectors.** The docs list the music verbs as [`MUSIC_CAPABILITIES`](custom_components/thalovant/music.py) and `SHARED_CAPABILITIES` have them, `targets` is named as not carried (`NOT_CARRIED`), and [`tests/music_vectors.json`](tests/music_vectors.json) is described as this repository's own copy (findings H4 and H6 above; [`tests/test_music_contract.py`](tests/test_music_contract.py)).
