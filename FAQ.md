Last Edit: Claude Fable 5.2 - 2026-11-13 - Motive: 0.5.0 after the 2026-11-13 recheck: what changed, why a room toggles only its lights, why a cover or a lock is refused aloud, the volume cap, relays and scripts, the removed `all` target, the test vectors.

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

**Why did it say it could not find a song that is in Music Assistant?** The name is searched with `music_assistant.search` and must be close to the title (60 percent similar); say the artist too.

**What changed in 0.5.0?** Structured actions and music (new), and the fixes of the 2026-11-13 recheck: a room named alone is its lights, covers are sensitive unless they are window coverings, a refused sensitive action is answered instead of being passed to Assist, the `all` target is gone, and a **Highest volume** option. See [CHANGELOG.md](CHANGELOG.md).

**Why did "toggle the garage" only toggle the light?** By design since 0.5.0. A room or a floor named alone means its lights (`DEFAULT_DOMAINS` in [`actions.py`](custom_components/thalovant/actions.py), `_room_default()`), whether the hub read "garage" as a room or as a name. Before, a name that turned out to be a room reached every light, switch, fan, helper and cover in it. Say the device ("toggle the freezer") or the kind ("the garage plugs").

**Why does it say "sensitive actions are turned off for this home"?** You asked for a lock, an alarm, a siren, a valve, or a cover that is not a window covering, and **Allow locks, alarms, ...** is off in the integration's options. The request was refused and was not passed to Assist. Turn the option on if a voice may do these in your home.

**My blinds stopped opening by voice. Why?** A cover is a window covering only when its device class is `awning`, `blind`, `curtain`, `shade` or `shutter` (`SAFE_COVER_CLASSES`). A cover with no device class is treated like a garage door, because many garage doors have none. Set the device class in Home Assistant (Settings, Entities, the entity, *Show as*), or turn the sensitive option on.

**Is my garage door safe if it is a relay or a script?** No more than any switch or script. The integration cannot tell that `switch.garage_opener` or a script opens a door, so it carries them out when they are exposed to Assist and named exactly, sensitive option or not (`test_known_limit_a_relay_or_a_script_named_exactly_is_carried_out` in [`tests/test_action_bounds.py`](tests/test_action_bounds.py)). A room or floor name no longer reaches them. Do not expose to Assist what a voice must not operate.

**Can I stop voice requests from turning the music all the way up?** Yes: **Highest volume (percent)** in the options. A structured request for more, as a level or by steps, is set at the cap and answered "The volume is at 60 percent, the highest allowed here." It applies to every media player a structured action reaches. It does not limit a sentence Assist handles itself, the volume buttons, or automations.

**Does "turn off everything" work?** Not as a structured action: the `all` target was removed in 0.5.0 (no Thalovant skill used it, and it reached up to 50 entities of a domain). The sentence goes to Assist, which decides.

**Are the music tests the same as the bridge's?** No. [`tests/music_vectors.json`](tests/music_vectors.json) is this repository's own copy, in the shape `world` + `cases`; the connector spec's vectors are organised as `validation` and `behavior`. See [docs/music.md](docs/music.md#test-vectors-what-they-are).
