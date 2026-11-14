Last Edit: Claude Fable 5.2 - 2026-11-13 - Motive: follow-ups of the 2026-11-13 recheck: household-marked sensitive entities, `all` out of the spec, vectors generated from the spec, the cap for Assist's own path.

# Suggestions

## Intercom (0.4.0)

**Cut the 0.4.0 release when the platform is ready to switch Intercom on.** Problem:
the SDK (`thalovant` 0.12.0) is released and `manifest.json` pins it, but the
platform ships Intercom switched off, so a user who turns the options on today gets
"Intercom is rolling out on Thalovant and is not switched on yet" and a Repairs
notice. Nothing breaks, but the feature does nothing yet. Proposed: release 0.4.0
(it is safe off) and say in the release notes that Intercom is rolling out; or hold
the release until the platform operator turns the switch on. Impact: a release now
costs support questions ("why does announce say not switched on?") answered by the
README, the FAQ and the notice itself; holding costs users the other 0.4.0 changes
(none besides Intercom).

**Give the SDK a public way to update a connection.** Problem:
[`ThalovantApi.set_connection_can_play()`](custom_components/thalovant/api.py) reads a
connection with the public `get_client()` and writes it with the SDK's private
`_request()` (marked "SDK GAP"; SDK 0.12.0 has no public client update, checked on the
released package). Proposed: an `update_client()` (whole spec with `If-Match`, or a
merge of `spec.intercom`) in the SDKs, called from `api.py`; the guard
[`test_the_private_write_is_in_one_place`](tests/test_api_intercom_sdk.py) fails when
one exists. Impact: one place for the etag and 412 handling, no private call; small.

**Confirm the hub delivers `speak` to a Home Assistant link.** Problem: the platform now
accepts `spec.intercom.can_play` on a Home Assistant connection (the one key a caller
may write) and lists it as a speaker only with it, which the integration declares. The
remaining question is the hub skill: it learns a speaker's peer from the messages it
hears, and Home Assistant sends none that the skill reads as an utterance. Proposed:
check, on a real hub, that an announcement to a `home_assistant` speaker arrives as a
`speak` with `data.meta.dialog == "intercom.announce"` and
`data.meta.intercom.{id, priority}` (what `parse_announcement()` accepts), and if the
skill needs a hello from the connection, tell the integration the message to send
once. Impact: it is what makes **Play announcements on this Home Assistant** work end
to end.

**Use `policy_synced` and the `kind` of the speaker list.** Problem: `thalovant.list_speakers`
returns `policy_synced` and each speaker's `kind` and `can_play`, but nothing acts on
them. Proposed: when the per-speaker entity model below exists, grey out the speakers
that cannot play, and show "changes may take a moment to reach the home" while
`policy_synced` is false. Impact: friendlier, no new request.

**Follow announcements from the platform's stream instead of polling.** Problem: an
urgent announcement that is sending is read every 5 seconds. Proposed: consume
`intercom.announcement.updated` from the SSE stream when an SDK offers it. Impact:
fewer requests, faster events.

**One entity per speaker.** Problem: a service field cannot be filled from a live list,
so `names` is typed. Proposed: a `notify` entity (or a device) per speaker and room,
created from `thalovant.list_speakers`, so a speaker is picked from a list and gets an
area. Impact: friendlier targeting; needs a stale-device policy.


## Earlier suggestions

**Take the code exchange from the SDK once it has one.** Problem: Link
account's exchange (`ThalovantOAuth2Implementation.async_resolve_external_data()`
in [`oauth.py`](custom_components/thalovant/oauth.py)) talks to
`/v1/auth/native/token` directly, outside [`api.py`](custom_components/thalovant/api.py),
the integration's only door to the SDK. SDK 0.10.0 has no exchange for a
caller-owned redirect. Proposed: when a pinned SDK exposes one, call it from
`api.py` and keep the Home Assistant implementation for the URL and state.
Impact: one parser for token answers and one error mapping, shared with the
other SDKs; small change, covered by the existing flow tests.

Private link setup currently requires four connection values from the hub
operator plus the approved Voice ID. If more private hubs use this flow,
consider an operator tool that supplies those values through a secure setup
package. Keep the same WSS origin, separate client identity and command scope
checks. This would reduce manual entry without expanding who can control Assist.
See [`ThalovantConfigFlow.async_step_self_hosted()`](custom_components/thalovant/config_flow.py).

A public SDK property for the original context would give authorization
consumers a stable way to read the sender before local event normalization.
Keep the serialized targeted request and reply regression when upgrading SDKs.
[Transport regressions](tests/test_self_hosted_transport.py).


## Close the Low findings of the 2026-11-13 security review

**Problem.** The normal link trusts the hub's `thalovant.home.request` completely: no source check, no
replay cache, and Home Assistant's shared session follows a redirect on the websocket upgrade
([AUDIT.md](AUDIT.md)). Each is stopped elsewhere (Noise session, key pin) but the integration should not rely on
that for the one path that can change a house.

**Proposal.** (1) Remember the last 256 `request_id`s and drop a repeat; (2) apply the self-hosted source and
session checks (`context.source == "thalovant.home.router"`, session `home-<request_id>`) to every link; (3) build the
link's session with a trace config that rejects redirects, as `self_hosted.async_create_session` does.

**Impact.** About 60 lines and three tests. No behaviour change for a healthy hub.

## Music

**Standalone bridge for households without Home Assistant.** Problem: this path needs Home Assistant. Proposed: `thalovant-music-bridge`, an outbound-only LAN client that executes the same actions (same `tests/music_vectors.json`) directly against Music Assistant. Impact: Music Assistant-only homes get the same voice control.

## After the 2026-11-13 recheck (0.5.0)

**Let the household mark entities as sensitive.** Problem: a relay that opens a garage door is a `switch`, and a
script can do anything; `_is_sensitive()` in [`actions.py`](custom_components/thalovant/actions.py) cannot recognise
either, so both are carried out with the sensitive option off when exposed to Assist and named exactly
([`test_known_limit_a_relay_or_a_script_named_exactly_is_carried_out`](tests/test_action_bounds.py)). Proposed: an
option holding a list of entities (an entity selector, several) that are treated as sensitive whatever their domain:
refused with the option off, one at a time with it on. Impact: about 40 lines in `actions.py`, `config_flow.py` and the
strings, five tests; closes the last two cases of the recheck's proof of concept. A product decision (one more option
on a public integration), so it was not taken here.

**Take `all` out of the connector spec's `home_assistant` target.** Problem: the spec (0.4.0) still lists `all` among
the target's properties, so the router validates and forwards it; this integration no longer accepts it (`TARGET_KEYS`).
Proposed: remove it from the spec so an action carrying it is refused at the hub. Impact: one line of the spec and its
vectors; `tests/test_sensitive_verbs.py::test_the_target_domains_are_exactly_the_specs` already ties the domain list.

**Generate `tests/music_vectors.json` from the spec, or delete it.** Problem: it is a hand-kept copy in an older shape;
the comparison with the spec's `behavior` list runs only where the spec package is installed, which this public
repository's CI cannot do (the spec is private). Proposed: publish the spec's vector file (it holds no secret) and
read it in the tests, or vendor it with a recorded hash and version. Impact: the two executors are provably held to
one file again.

**Cap the volume on Assist's own path too.** Problem: `max_volume` limits structured actions; "set the kitchen speaker
to 100 percent" as a sentence that Assist handles is not limited. Proposed: nothing in this integration can limit
Home Assistant's own intents; document it (done) and consider sending every volume sentence as a structured action
from the skills. Impact: a skill change, not an integration change.

**Say the level in every volume answer.** Problem: a volume action answers "Done." unless the cap lowered it. Proposed:
answer the level always (the bridge route does). Impact: one string per language, changes what users hear.
