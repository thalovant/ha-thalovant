Last Edit: Claude Sonnet 5.5 - 2026-11-13 - Motive: documentation sweep: structured actions, sensitive actions and the alarm code, every option, diagnostics redaction, release state, music corrections.

# FAQ

**Is Intercom a safety system?** No. It is a convenience: it is not a certified
safety system and does not replace smoke or carbon monoxide alarms, medical alert
devices or emergency services. It can fail silently (Home Assistant, the internet,
Thalovant, the hub or a speaker down; Do Not Disturb; a speaker not set to receive;
nobody home). See [the guide](docs/announcements.md).

**Is Intercom available to me yet?** Not necessarily. It is rolling out: Thalovant
ships it switched off for the whole platform and turns it on deliberately, so it
may not be enabled on your hub or account yet. While it is off the announce
actions answer "Intercom is rolling out on Thalovant and is not switched on yet.
Nothing was sent", Repairs shows the same, `thalovant.list_speakers` still answers
(`unavailable_reason: platform`) and `thalovant.cancel_announcement` still works.
Nothing is wrong on your side and nothing is retried; you can leave the options on.

**What changed in 0.4.0?** Intercom: `thalovant.announce`,
`thalovant.cancel_announcement`, `thalovant.list_speakers`, an Intercom notify
entity, and playing the hub's announcements on media players. All off by default;
an entry that never turns them on behaves as in 0.3.0. See
[`IntercomController`](custom_components/thalovant/intercom.py) and
[`IntercomSpeakerHandler`](custom_components/thalovant/speaker.py).

**Why does turning on announcements open a re-authentication request?** Sending
needs the `intercom:read` and `intercom:send` permissions (and `intercom:urgent`
for urgent), which the sign-in did not ask for. The request asks only for those;
nothing is saved until you approve, and the option stays off if you decline. See
[`ThalovantConfigFlow.async_step_intercom_consent()`](custom_components/thalovant/config_flow.py).

**The service says Intercom "is rolling out" or "is not available yet".** That is
`intercom_disabled_platform` (503) or `intercom_not_configured` (503): the platform
switch is off, or Thalovant has not finished setting Intercom up. See the first
question. It is not a failure of this Home Assistant, and nothing was sent.

**An urgent announcement says it needs a permission, is busy, or needs a skill.**
`urgent_scope_required`: the token lacks `intercom:urgent` (turn **Allow urgent
announcements** off and on again; the plan must allow it). `intercom_urgent_busy`:
2 urgent announcements are already repeating on the hub; cancel one or wait the
seconds it says. `skill_not_installed`: the hub has no Intercom skill yet. Nothing
was sent in any of these.

**It says a speaker "cannot play speech".** `not_a_speaker`: that connection has
`can_play: false`. `thalovant.list_speakers` shows `kind` and `can_play`. A Home
Assistant link is a speaker only once Home Assistant told Thalovant it can play
(`spec.intercom.can_play`, done when **Play announcements on this Home Assistant**
is on), and the owner switched receiving on.

**Why is my message refused locally?** The platform's own text rule, checked first
so a refusal costs no request: 1 to 280 characters after NFC normalisation and
trimming; no `<` or `>`; no control, bidirectional or other invisible characters
(zero-width joiner and non-joiner are fine); no private-use characters. Line breaks
and tabs become spaces.

**The service says "Announcements are turned off".** Turn on **Send announcements**
in the integration's options. With several hubs, name one with `config_entry_id`.

**The service says it "may still have been spoken". Should I send it again?** Look
in the Thalovant dashboard first. The integration never retries: a 502 means the
hub did not confirm, and it can have spoken anyway. Each call is a new announcement
with its own idempotency key; the same key is never reused.

**Can I stop an urgent announcement that repeats?** Yes: `thalovant.cancel_announcement`
with the id the announce action returned (it works even if announcements were turned
off since). Also the hub's Intercom switch in the dashboard, a speaker's receive
switch, Thalovant's platform switch, and saying an acknowledgement at a speaker.

**How do I find the names to announce to?** Call `thalovant.list_speakers` in
**Developer tools** > **Actions**. Home Assistant cannot fill a field from a live
list, so `names` is typed; a speaker can be named by its name, slug or id.

**Why is the Intercom notify entity missing?** It exists once **Send announcements**
is on, and it is disabled by default: enable it under the hub's device.

**Is the text stored or logged?** Not by this integration (no log, event, repair,
error or diagnostics holds it) and not by Thalovant (it keeps a keyed hash and the
length). Home Assistant's automation traces keep what an automation was told to say,
and a speaker's text to speech may cache or log what it says.

**The hub's announcements are not played on my speakers.** Check **Play announcements
on this Home Assistant** has an available media player or area and a text to speech;
that the hub's owner switched **receive** on for this connection in the Thalovant
dashboard; and that Repairs shows no "was not told that ... can play" notice.
Diagnostics list what was ignored and why.

**Does an urgent announcement play louder?** No. Playing never changes a volume.

**Why 20 a minute and 5 an hour?** This integration's own limits, below the
platform's, so a runaway automation is stopped before it reaches the household.

**What changed in 0.3.0?** The first step offers **Link account** (the
default) and **Link with a code instead**. Link account approves in the
browser and comes back through My Home Assistant; the code is the device
login of 0.2. See
[`ThalovantConfigFlow._async_start_link_account()`](custom_components/thalovant/config_flow.py).

**What does Link account add over a code?** No code to type, and only the
Home Assistant that started the setup can use the approval: the request is
signed with its own secret, and the code is useless without the PKCE verifier,
which Home Assistant sends only to Thalovant's token endpoint, never through
the browser. Neither method makes approving somebody else's
request safe, so approve only sign-in requests you started. Thalovant
completes either only when it is approved from the same network as the
Home Assistant that asked, so a link sent to someone on another computer or
network gives them nothing. See [`oauth.py`](custom_components/thalovant/oauth.py).

**Link account says Thalovant did not accept the approval.** If it says the
approval came from a different network (`link_wrong_network`, the API's code
`exchange_network_mismatch`), it was given over another network than
Home Assistant's, for example mobile data, a VPN or remote access: link again
from a phone or computer on Home Assistant's network. Otherwise
(`link_failed`) the approval expired after a minute or was already used:
try again. See
[`ThalovantConfigFlow.async_step_creation()`](custom_components/thalovant/config_flow.py).

**Link account offers a code instead. Why?** My Home Assistant is not turned
on, so Home Assistant's redirect is not `https://my.home-assistant.io/redirect/oauth`,
the only one Thalovant answers. Add `my:` (or keep `default_config:`) and
restart, or link with the code.

**Do entries linked with a code before 0.3.0 keep working?** Yes. Both
methods store the same token form and the entry version is unchanged; reauth
offers Link account too. See
[`test_entries_are_the_same_either_way`](tests/test_link_account.py).

**Is there a refresh token?** No. Either sign-in gives the same setup token,
valid for a year; approving again replaces it for every hub of the account.

**Why doesn't my private Christmas hub appear when I sign in?** The account
flow lists hubs registered with the Thalovant control plane. Choose **Link a
self-hosted Christmas hub** for an operator-issued private connection. See
[`ThalovantConfigFlow.async_step_self_hosted()`](custom_components/thalovant/config_flow.py).

**Can I renew the private credentials?** Reauthentication accepts replacement
Home Assistant credentials for the same endpoint and authorized Voice ID.
Check that the hub operator has admitted the replacement client first.

**Why could the hub show connected while Christmas lighting stayed idle?**
Version 0.2.3 checked the SDK's local node address where it expected the router
source. Version 0.2.4 reads the original router source. An existing private link
keeps its credentials and Voice ID when the integration is updated.

**Who revokes private credentials?** The hub operator revokes the dedicated
client. [`async_remove_entry()`](custom_components/thalovant/__init__.py)
removes the local entry and its Noise state. See the [setup guide](README.md).

**Can I play music from a Thalovant device through Home Assistant?** Yes, if Home Assistant has the Music Assistant integration and its players are exposed to Assist: "play Adam's Song on the kitchen speaker". See [docs/music.md](docs/music.md).

**Why did it say it could not find a song that is in Music Assistant?** The name is searched with `music_assistant.search` and must be close to the title (60 percent similar, `MIN_MATCH` in `music.py`, or every word of your request must be in the title); say the artist too. Music is on `main` after 0.4.0 and not released.

## Structured actions, options and diagnostics (on `main` after 0.4.0, not released)

**Which version has structured actions and music?** Neither is in 0.4.0, the last
release (2026-11-12). They are merged on `main` (PRs #30, #32 and #31);
`manifest.json` still says 0.4.0. See [README.md](README.md#structured-actions).

**What is a structured action?** Next to the sentence, a hub request can carry a
capability (what), a target (which entity, area, floor or the speaker's room) and
a value. The integration resolves it among the entities exposed to Assist and
calls their services, instead of leaving the sentence to Assist's parser.
`actions.resolve()`, `actions.async_execute()`.

**What does "safe defaults" mean?** Structured requests are **on**; sensitive
ones (locks, alarm panels, garage doors, gates, windows, valves, sirens) are
**off**; the alarm code is empty so nothing disarms; only entities exposed to
Assist are ever reached; and when the integration cannot resolve exactly what
was asked it does nothing structural and lets Assist have the sentence.
(`CONF_STRUCTURED_ACTIONS`, `CONF_STRUCTURED_SENSITIVE`, `CONF_ALARM_CODE` in `const.py`.)

**Why did "dim the lamp" turn the lamp on?** A relative change starts from the
real state. An off light counts as brightness 0, so dimming it by 20 asks for 1
percent, and the light comes on at 1 percent (`actions._brightness`, called
directly with an off light on 2026-11-13). "Brighter" on an off light gives 20
percent. Not fixed; see AUDIT.md.

**Which verbs are sensitive, and what do they need?** `lock`, `unlock`, `arm`,
`disarm` always; a siren on, off or toggled; a valve opened or positioned; a
garage, gate, door or window cover opened, positioned or toggled. They need the
option **Allow locks, alarms, garage doors, gates, valves and sirens**, an entity
exposed to Assist, and exactly one entity (never a room, a floor or "all"). A
disarm also needs the **Alarm code**. Off, they go to Assist as words.
(`SENSITIVE_VERBS`, `_is_sensitive()`, `_one_at_a_time()`.)

**Why will it not "unlock the kitchen" or "run all the scripts"?** A sensitive
action and any action on a scene, script, automation or button is only carried
out structurally for one named entity; "all the automations" must not switch off
the household's automations (`_one_at_a_time()`, fixed by PR #32,
`test_scripts_and_automations_are_run_or_switched_one_at_a_time`).

**Where is the alarm code kept, and does a diagnostics file show it?** In the
entry's options, in clear, in Home Assistant's `.storage` like every
integration's secrets; never sent by the hub. Diagnostics redact it since PR #32
(`TO_REDACT`; `test_diagnostics_never_hold_the_alarm_code`). No release carried the
option without the fix (both are unreleased), but a diagnostics file made from `main`
between PRs #30 and #32 may hold the code: if you pasted one, change the code.

**What does a diagnostics file hold?** The entry's data and options with the
tokens, credentials, ids, hub name, title, alarm code and announcement players,
areas and text to speech redacted; the connection state; counters of requests by
outcome; Intercom counters. No sentence, answer or announcement.
[README.md](README.md#diagnostics).

**What are all the options?** See the table in [README.md](README.md#options) and
[QUICK_FACTS.md](QUICK_FACTS.md#options-all-of-them): conversation agent, send
announcements, allow urgent announcements, play announcements (with players, areas
and text to speech), carry out structured requests, allow sensitive actions, alarm
code.

**It said "Sorry, I could only do part of that." Why did it not just try again?**
A service failed after another had already changed an entity. Asking Assist as
well would run the intent again on everything, doubling a relative step and
undoing a toggle, so the integration reports it as partial and stops
(`test_a_failure_after_part_of_it_is_done_is_reported_not_retried`).

**Does the volume of "the kitchen" go to Music Assistant?** Only for the speaker's
own room. A named target for volume, mute or playback is resolved among all
exposed media players, which can include a Chromecast of the same name
([docs/music.md](docs/music.md)).

**Does the bridge use `tests/music_vectors.json`?** No. The bridge's tests read
the connector spec's copy; the two agree case for case today and nothing checks
they stay equal.
