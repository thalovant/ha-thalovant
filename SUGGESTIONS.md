Last Edit: Claude Sonnet 5.5 - 2026-11-13 - Motive: security review follow-ups (replay cache, redirect refusal, source check).

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
