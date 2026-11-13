Last Edit: Claude Sonnet 5.5 - 2026-11-13 - Motive: documentation sweep: pointer to the other options in the same form and to the diagnostics page; Intercom content unchanged (reviewed against the options code, no disagreement).

# Announcements (Intercom)

> **Safety notice.** Intercom is a convenience, **not a certified safety
> system**. It does not replace smoke or carbon monoxide alarms, medical alert
> devices or emergency services, and it can fail silently: Home Assistant, your
> internet connection, Thalovant, the hub or a speaker can be down, a speaker can
> be set not to receive, Do Not Disturb can skip an announcement, and nobody may
> be home to hear it. Never rely on it for anything that could hurt someone if it
> were not heard.

> **Intercom is rolling out, and may not be enabled on your hub or account yet.**
> Thalovant ships Intercom switched off for the whole platform and turns it on
> deliberately. Until it does, every announcement is refused ("Intercom is
> rolling out on Thalovant and is not switched on yet. Nothing was sent"), a
> **Repairs** notice explains, and nothing else changes: nothing is sent,
> retried or crashed, `thalovant.list_speakers` still answers (with
> `unavailable_reason: platform`) and `thalovant.cancel_announcement` still works.
> Turning the options on before then is safe.

Announcements are **off until you turn them on**, in three separate steps, and an
entry that never turned them on behaves exactly as it did before 0.4.0.

- **Send** a short text to speakers in your home from an automation, a script or
  the notify entity: `thalovant.announce`.
- **Play** the announcements your hub makes on this Home Assistant's media
  players, so a speaker you already own can be one of Thalovant's speakers.
- Both are announce-only. Nothing here opens a microphone or records speech.
  While an urgent announcement repeats, the hub only checks whether a reply
  heard by its own voice pipeline is an acknowledgement ("I'm okay", "got it").

## What you need

| Need | Where |
| --- | --- |
| Thalovant itself has Intercom switched on | **Not yet, for everyone: it is rolling out.** It is a platform switch that ships off. While it is off, announcing is refused and nothing is sent, and Home Assistant says so in Repairs. |
| A Thalovant plan that includes Intercom | The Thalovant dashboard. The Free plan and the legacy Connect plan do not. |
| A hub that is not a kid hub or a public hub | Intercom is never available on those. |
| Intercom switched on for the hub | The hub's **Intercom** tab in the Thalovant dashboard, by the hub's owner or a manager. |
| Each speaker set to **receive** | The same tab. A speaker that does not receive is never spoken to, even for an urgent announcement. A connection that cannot play speech (`can_play` false) cannot be set to receive. |
| An owner or a manager of the account | Announcing, switching Intercom on and changing a speaker are for them. A plain member of the account can read, and Thalovant refuses their announcement (403). |

## Turn it on

Open the integration and select **Configure**. The same form also holds the conversation agent and the structured-action options (carry out structured requests, allow sensitive actions, alarm code): [README: Options](../README.md#options).

| Option | What it does |
| --- | --- |
| **Send announcements** | Adds the actions `thalovant.announce`, `thalovant.cancel_announcement` and `thalovant.list_speakers`, and an Intercom notify entity (disabled until you enable it). |
| **Allow urgent announcements** | Lets an announcement be urgent: it ignores Do Not Disturb and can repeat until somebody acknowledges it. Needs **Send announcements**. |
| **Play announcements on this Home Assistant** | Lets the hub play announcements on the media players, areas and text to speech you choose next. |

Turning on **Send announcements** (or **Allow urgent announcements**) asks
Thalovant for an extra permission first: `intercom:read` and `intercom:send`, and
`intercom:urgent` for urgent, which is asked for **only** when you turn **Allow
urgent announcements** on (an urgent announcement needs it in addition to
`intercom:send`; nothing implies it). Home Assistant opens a re-authentication request
(in a notification and under **Repairs**) that asks only for those, with the same
two ways to approve as when you linked (**Link account** or a code). Nothing is
saved until you approve. If you decline, or your plan is not granted the
permission, the option stays off.

Because signing in again replaces the account's token for every linked hub, the
new token also carries the permissions the link already had, and any Intercom
permission another entry of the account has on. With nothing turned on, a sign-in
asks for exactly what it always did (`hubs:read`, `clients:read`,
`clients:write`).

Turning an option off stops the integration using it at once. The token keeps the
permission until you re-link or remove the integration; to take it back sooner,
revoke the API token in the Thalovant dashboard.

## Sending

### `thalovant.announce`

| Field | Meaning |
| --- | --- |
| `message` | Required. 1 to 280 characters, counted after Unicode NFC normalisation and trimming. Line breaks and tabs become spaces. `<` and `>`, control, text-direction (bidirectional) and other invisible formatting characters (the zero-width joiner and non-joiner are allowed), private-use characters, lone surrogates and line or paragraph separators are refused, never silently dropped. This is the platform's own rule, checked here first, so a refusal costs no request and never repeats the text. |
| `target` | `all` (default), `speakers`, `rooms` or `groups`. |
| `names` | The speakers, rooms or groups, when the target is not `all` (at most 50, each at most 64 characters). A speaker can be given by its name, slug or id; a name shared by two speakers is refused. |
| `priority` | `normal` (default) or `urgent`. Urgent needs **Allow urgent announcements** and the `intercom:urgent` permission. |
| `repeat_times`, `repeat_interval` | Urgent only, both together: 1 to 10 times, 5 to 120 seconds apart. It repeats until somebody acknowledges it, it is cancelled, or the repeats run out. |
| `language` | A tag such as `en-US` or `fr`. Leave empty for the hub's default. |
| `wait` | For an urgent announcement that repeats: hold the action until it ends, for at most five minutes. |
| `config_entry_id` | Which linked hub, when more than one has announcements on. |

`target: all` with names, or any other target without names, is refused rather
than guessed. Use `thalovant.list_speakers` (an action that returns data) in
**Developer tools** > **Actions** to see the speakers, rooms and groups that
exist, with each speaker's `kind`, whether it `can_play` speech, who is online and
who receives. Home Assistant cannot fill a service field from a live list, so the
names are typed. A connection with `can_play: false` (a Home Assistant link that
has not been set up to play, say) is listed but cannot receive and is never part of
`all`, a room or a group; naming it is refused (`not_a_speaker`). The answer also
carries `policy_synced` (false while a change to who receives may take a moment
to reach the home) and `unavailable_reason` (`platform` while Intercom is not
switched on, or `plan`, `kid_hub`, `public_hub`, or none).

The action returns, when you ask for a response, only ids and counts:

```yaml
announcement_id: 0fe8d3c2-6a52-4d3b-9a4e-5c1f0b7a9e11
status: completed        # sending, completed, partial, failed or cancelled
priority: normal
deliveries:
  total: 3
  by_status: {delivered: 2, offline: 1}   # also acked, skipped_dnd, skipped_not_receiving, failed
acked_by: null           # the name of the speaker that acknowledged, if one did
replayed: false          # true: Thalovant handed back one it already had; nothing new was sent
```

`completed`, `partial` and `failed` are Thalovant's own summary of the
deliveries, and none of them means that somebody heard it: `delivered` means the
hub handed the speech to that speaker's connection, there is no playback
receipt, and `failed` is not proof that nothing was spoken. Each delivery is
`delivered`, `acked`, `offline`, `skipped_dnd` (Do Not Disturb),
`skipped_not_receiving` or `failed`. An announcement with nobody to speak to
returns `failed`, with each reason in the counts.

### The notify entity

With **Send announcements** on, an entity called **Intercom** exists and is
**disabled by default**. Enable it under **Settings** > **Devices & services** >
**Thalovant** > the hub, and `notify.send_message` makes a normal announcement to
every speaker that receives. The title is not spoken.

### The event

When a status is known to have changed, Home Assistant fires
`thalovant_announcement_updated` with `announcement_id` and `status` and nothing
else: never the text. An urgent announcement that is still sending is read every
five seconds, for as long as it can last, so an automation can wait for
`completed`, `partial`, `failed` or `cancelled`.

### Stopping a repeating announcement

`thalovant.cancel_announcement` with the `announcement_id` stops an urgent
announcement that is still repeating. It returns `hub_confirmed`: `false` means
the hub could not confirm, and speech already queued on it may still play (the
announcement is `cancelled` in Thalovant's records either way). It works even if
**Send announcements** was turned off since, as long as the token may send, and
even while Thalovant's platform switch is off (then `hub_confirmed` is `false` and
no hub was called). An announcement that is no longer repeating cannot be
cancelled; the error gives its current status. The other controls are Thalovant's platform switch, the per-hub switch
in the dashboard, a speaker's **receive** switch, and a spoken acknowledgement at
a speaker.

### What happens when something goes wrong

| What you see | What it means | What to do |
| --- | --- | --- |
| "may still have been spoken" with an announcement id (a 502 from the hub) | Thalovant could not reach the hub for the answer. The text may or may not have been spoken. | Look at the announcement in the Thalovant dashboard before sending again. Home Assistant does **not** retry. |
| "not known whether the announcement was made" | Thalovant did not answer in time. | Same: check before sending again. |
| "limit": 20 a minute, 5 urgent an hour | This integration's own limit, below the platform's (20 a minute, 10 urgent an hour per hub). | Slow the automation down. Nothing was sent. |
| "Thalovant's announcement limit was reached ... try again in N seconds" | The platform's limit (429, with `Retry-After`). | Wait the time it says. Nothing was sent. |
| "Intercom is rolling out on Thalovant and is not switched on yet" (and a **Repairs** notice) | The platform switch is off (`intercom_disabled_platform`), or Thalovant has not finished setting Intercom up (`intercom_not_configured`: "not available yet"). Nothing is wrong on your side. | Nothing: it is rolling out. Nothing was sent. Home Assistant checks again at start and when you announce. |
| "Intercom is switched off for the hub" / "never available on the kid hub / public hub" / "not part of the plan" | A **Repairs** notice names the reason (`intercom_disabled`, `intercom_unavailable` with its `reason`, `plan_limit`). | Follow its text; the first is switched on in the dashboard by the hub's owner or a manager. |
| "has not granted ... the permission to send announcements" | The token lacks `intercom:send`. | Turn **Send announcements** off and on again to approve it. |
| "has not granted ... the permission for urgent announcements" | The token lacks `intercom:urgent` (`urgent_scope_required`); the plan must allow it. Nothing is spent. | Turn **Allow urgent announcements** off and on again, or send a normal announcement. |
| "already has the most urgent announcements it allows repeating" | A hub may have 2 urgent announcements repeating, the platform a fixed number per replica (`intercom_urgent_busy`, 429). | Stop one with `thalovant.cancel_announcement`, or wait. Nothing was stored. |
| "The Intercom skill is not installed on the hub yet" | An urgent announcement needs the skill on the hub's runtime (`skill_not_installed`). | Switch Intercom on for the hub, wait for the skill, try again. Nothing was sent. |
| "A speaker you named cannot play speech" | A named connection has `can_play: false` (`not_a_speaker`). | `thalovant.list_speakers` shows it. Name one that can play. |
| "More than 50 speakers" | `all`, a room or a group resolved to more than 50 speakers (`too_many_targets`). | Name a smaller room or group, or at most 50 speakers. |
| "The hub is locked" | `hub_locked`: nothing was changed or sent. | Unlock it in the dashboard. |
| "only lets an owner or a manager of the account announce" | A plain member linked this Home Assistant (403). | Link it with an owner's or manager's account. |

Every call makes a **fresh idempotency key**, and the integration never retries
by itself. A second call with the same words is a second announcement. A failed
announcement is not resent, and a key is never reused: to send it again, call the
action again once you know nothing was spoken.

## Receiving: Home Assistant as a speaker

Turn on **Play announcements on this Home Assistant** and choose where:

- **Media players** and/or **Areas** (every media player in the area, by its own
  area or its device's). A player that is unavailable is skipped.
- **Text to speech**: leave empty for Home Assistant's default (the cloud's when
  there is one, otherwise the first by entity id).

Then, in the Thalovant dashboard, the hub's owner switches **receive** on for this
Home Assistant's connection on the **Intercom** tab. Home Assistant tells
Thalovant that the connection can play (`spec.intercom.can_play: true`, written to
the connection with `PATCH /v1/clients/{id}`) when it starts and when you save the
options, and `false` when you turn playing off. A Home Assistant connection is a
speaker only once it has said so: until then Thalovant lists it with `can_play:
false` and refuses `receive` for it. If Home Assistant could not tell Thalovant,
Repairs says so. Delivering the hub's announcements to a Home Assistant link also
depends on the hub's Intercom skill, which is rolling out with the rest. Consent stays
with the owner: turning the option on here does not make a speaker receive.

When the hub sends an announcement, Home Assistant:

1. accepts only a `speak` message whose `meta.dialog` is `intercom.announce`,
   with an announcement id of a safe shape, a priority of `normal` or `urgent`
   and a text that is fit to say, on the hub's own authenticated link. Anything
   else is ignored. A private (self-hosted) link never plays announcements;
2. removes control, text-direction and angle-bracket characters (a text to speech
   that reads markup could take them for it) and ignores a text that is empty or
   longer than 280 characters once cleaned, rather than cutting it;
3. plays at most 6 new announcements a minute, a normal announcement once, and an
   urgent one as often as the platform lets it repeat (10 times); at most 4 plays
   run at once;
4. says the text with `tts.speak` on the chosen players, in the message's
   language when the text to speech speaks it, **at each player's current
   volume**: it never changes a volume, urgent or not, and asks for no cached
   audio file;
5. does all of that in background tasks, so a slow player never holds up the
   link to the hub.

Diagnostics hold only counters (played, failed, ignored and why), and redact the players, areas and text to speech you chose ([README: Diagnostics](../README.md#diagnostics)).

## Automation examples

A door left open:

```yaml
automation:
  - alias: "Front door left open"
    triggers:
      - trigger: state
        entity_id: binary_sensor.front_door
        to: "on"
        for: "00:05:00"
    actions:
      - action: thalovant.announce
        data:
          message: "The front door has been open for five minutes."
          target: rooms
          names: [kitchen, entrance]
```

Every speaker, from any notify action:

```yaml
actions:
  - action: notify.send_message
    target:
      entity_id: notify.maison_intercom   # the Intercom entity, once enabled
    data:
      message: "Dinner is ready."
```

An urgent announcement that you stop yourself, using the id it returns:

```yaml
actions:
  - action: thalovant.announce
    data:
      message: "The garage door is still open."
      priority: urgent
      repeat_times: 5
      repeat_interval: 30
    response_variable: alert
  - wait_for_trigger:
      - trigger: state
        entity_id: binary_sensor.garage_door
        to: "off"
    timeout: "00:03:00"
    continue_on_timeout: true
  - action: thalovant.cancel_announcement
    data:
      announcement_id: "{{ alert.announcement_id }}"
    continue_on_error: true     # it may have ended already
```

React to how an announcement ended:

```yaml
triggers:
  - trigger: event
    event_type: thalovant_announcement_updated
    event_data:
      status: failed
```

### A smoke, carbon monoxide or fall sensor

You can announce from such a sensor, but **keep your real alarms and devices**.
Intercom is an extra voice in the house: it can stay silent if Home Assistant, the
internet, Thalovant, the hub or a speaker is down, if the automation does not run,
if Do Not Disturb skips a normal announcement, or if nobody is home. A fall sensor
can miss falls and can also report falls that did not happen. Use a
certified smoke or carbon monoxide alarm, a medical alert device and emergency
services for those, and treat an announcement as a way to tell the people around
you sooner, not as the alarm.

```yaml
actions:
  - action: thalovant.announce
    data:
      message: "The kitchen smoke detector is going off. Check it now."
      priority: urgent
      repeat_times: 3
      repeat_interval: 20
```

## Privacy

- The text goes from Home Assistant to Thalovant's API, to your hub, and to each
  speaker's own text to speech. Thalovant keeps a keyed hash of the text and its
  length, the targets and each speaker's result; it does not keep the text. Your
  hub's own message bus and each speaker's text to speech are outside the
  platform, and a text to speech may cache or log what it says.
- This integration never logs, stores, or puts the text in an event, a Repairs
  notice, an error message or diagnostics. It logs ids, outcomes and error types.
- Home Assistant itself keeps what an automation was told to say: automation
  traces, and the automation's own YAML. A message you template from sensor values
  is visible there.
- Intercom does not record or store speech. While an urgent announcement
  repeats, the hub only checks whether a reply that its voice pipeline already
  hears is an acknowledgement.

## Where it is in the code

| Part | Source |
| --- | --- |
| Options, the receive step and the re-consent request | `ThalovantOptionsFlow` (`async_step_init()`, `async_step_receive()`, `_async_finish()`) in `custom_components/thalovant/config_flow.py` |
| Re-consent (a reauth that asks for the extra scopes and stores the options on success) | `ThalovantConfigFlow.async_step_intercom_consent()`, `_async_finish_consent()` and `_wanted_scopes()` in `config_flow.py`; `scopes_for_options()` in `intercom.py`; `ThalovantOAuth2Implementation` in `oauth.py` |
| The actions | `async_setup_services()`, `async_get_controller()` and `_announce_request()` in `services.py` |
| Sending, cancelling, following, errors, repairs | `IntercomController.async_announce()`, `async_cancel()`, `_async_follow()`, `_error()`, `async_check_availability()` and `async_set_can_play()` in `intercom.py` |
| The text rules (the platform's own, checked against the SDK's `announcement_text()` by `test_the_text_rule_is_the_platforms`) | `validate_text()`, `clean_received_text()`, `validate_names()` in `intercom.py` |
| The notify entity | `IntercomNotifyEntity` in `notify.py` |
| Playing | `IntercomSpeakerHandler` (`async_handle_message()`, `_admit()`, `_async_players()`, `_async_tts_entity()`, `_async_play()`) and `parse_announcement()` in `speaker.py` |
| The SDK calls (all public, but one) | `ThalovantApi.announce()`, `cancel_announcement()`, `get_announcement()`, `get_intercom_settings()` and `list_intercom_speakers()` in `api.py`, which call the SDK's `announce`, `cancel_announcement`, `get_announcement`, `get_intercom_settings` and `list_intercom_speakers`; `_translate_intercom()` maps every problem code. The exception: `ThalovantApi.set_connection_can_play()` (SDK 0.12.0 has no public call that updates a connection, so it reads with `get_client()` and writes with the SDK's private `_request()`; marked SDK GAP, and the one place) |
| Tests | `tests/test_intercom.py`, `test_services.py`, `test_notify.py`, `test_speaker.py`, `test_intercom_options.py`, `test_intercom_setup.py`, `test_api.py`, `test_api_intercom_sdk.py` |

For the platform side see `[thalovant-api: docs/intercom.md]` (the HTTP routes,
limits, idempotency and cancel) and the Intercom guide of the `thalovant` Python
SDK (`[thalovant-python-sdk: docs/guides/intercom.md]`).
