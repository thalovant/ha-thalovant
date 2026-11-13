Last Edit: Claude Sonnet 5.5 - 2026-11-13 - Motive: documentation sweep: structured actions (capabilities, registry resolution, sensitive actions, alarm code, one at a time), every option with its default, diagnostics redaction, music pointer, release state (0.4.0 released; structured actions and music are on main, unreleased).

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/thalovant/.github/main/profile/assets/thalovant-logo-dark.png">
    <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/thalovant/.github/main/profile/assets/thalovant-logo-light.png">
    <img src="https://raw.githubusercontent.com/thalovant/.github/main/profile/assets/thalovant-logo-light.png" alt="Thalovant" width="320">
  </picture>
</p>

# Thalovant for Home Assistant

Say "turn off the kitchen light" to any Thalovant device, at home or away, and
Home Assistant does it.

This integration links your Home Assistant to your Thalovant hub. When a
Thalovant device hears something meant for your home, the hub passes the
sentence to Home Assistant, Assist handles it, and the hub speaks Assist's
answer on the device that asked.

- **Nothing to open.** Home Assistant connects out to the hub, the way a
  Thalovant satellite does. No port forwarding, no Nabu Casa, and no Home
  Assistant token ever leaves your home.
- **Assist decides.** Requests go to Home Assistant's conversation API, so only
  the entities you have [exposed to Assist][expose] can be controlled, and the
  answers are Assist's own.
- **Your agent.** Home Assistant's built-in agent answers by default. You can
  pick any other conversation agent you have installed.

Since 0.4.0 it can also, **only if you turn it on**, say a short text on your
hub's speakers (`thalovant.announce`) and play the hub's announcements on your
Home Assistant media players: see [Announcements](#announcements-intercom).

**Release state.** The last release is 0.4.0 (tag `v0.4.0`, 2026-11-12). The
structured actions and the music actions below are merged on `main` after that
release and are **not in a release yet**: `manifest.json` still says 0.4.0, and the
next release is expected to be 0.5.0 (not cut). Installing 0.4.0 from HACS does
not include them.
**Intercom is rolling out on Thalovant and may not be enabled for your account
or hub yet.** Until it is, the announcement actions say so and send nothing.

The [Link Home Assistant guide][guide] on docs.thalovant.com covers the same
steps with what each device sentence means when something goes wrong.

## Requirements

- Home Assistant 2026.9 or later.
- [HACS](https://hacs.xyz).
- A Thalovant account with at least one hub. On the Free plan, Home Assistant
  can only be linked to a public hub such as Daily Desk. The link doesn't count
  toward the plan's connections, so your phone or speaker keeps its place.
- [My Home Assistant][my] turned on, for **Link account**. It is part of
  `default_config:`; without it, link with a code instead.

## Installation

### With HACS

Thalovant is in the HACS default repository list, so there is nothing to add
by hand.

1. In Home Assistant, open **HACS** and search for **Thalovant**.
2. Open it and select **Download**.
3. Restart Home Assistant.

If your Home Assistant is set up for My Home Assistant links,
[this link][my-hacs] opens Thalovant in HACS, which is step 1.

### By hand

Copy `custom_components/thalovant` from this repository into the
`custom_components` folder of your Home Assistant configuration, then restart
Home Assistant.

## Linking your hub

Do this from a phone or computer on the same network as Home Assistant (your
home Wi-Fi, with any VPN turned off): Thalovant accepts the approval only from
Home Assistant's own network.

1. Go to **Settings** > **Devices & services**, select **Add integration**, and
   choose **Thalovant**.
2. Leave **Link account** selected and select **Submit**. Thalovant opens in a
   new browser tab.
3. Sign in to Thalovant if it asks, check that the request names
   **Home Assistant**, and approve it. The browser comes back to this
   Home Assistant through My Home Assistant (the first time, My Home Assistant
   asks for your Home Assistant's address), and the dialog moves on by itself.
4. Pick the hub whose devices should reach this Home Assistant. Hubs that can
   link come first. A hub that can't yet is marked "can't link Home Assistant
   yet", and picking it says so without creating anything.
5. Wait while the hub admits Home Assistant. It usually takes about a minute
   and a half. The integration is added once the hub is ready, and the link
   shows under **Connections** in the Thalovant dashboard with the type
   **Home Assistant**.

### Link with a code instead

Choose **Link with a code instead** in the first step when My Home Assistant
isn't set up, or when you would rather type a code. If you choose **Link
account** without My Home Assistant, the setup says so and offers the code.

1. Select **Submit**. Home Assistant shows a link and a code.
2. Open the link on a phone or computer on the same network as this
   Home Assistant, with any VPN off: Thalovant accepts a code's approval only
   from Home Assistant's own network. Sign in, check the code matches, and
   approve. The page names the request **Home Assistant** and marks it as a
   Thalovant-registered app. The dialog in Home Assistant moves on by itself.
3. Pick the hub and wait for it, as above.

### Why Link account is the default

**Link account** has no code to type, and only the Home Assistant that started
the setup can use the approval: the request is signed with its own secret, and
turning the approval into a token takes a key (a PKCE verifier) that
Home Assistant sends only to Thalovant when it asks for the token, never
through your browser. Spotify, Google, Netatmo and other cloud integrations
link accounts the same way. Both methods give Home Assistant the same token and
the same link.

Either way, approve only sign-in requests you started, and check that
My Home Assistant opens your own Home Assistant. Thalovant completes a link
only when the approval comes from the same network as the Home Assistant that
asked, so a link sent to someone on another computer or network gives them
nothing.

### What the setup asks for

| Field | What it means |
| --- | --- |
| How to link | **Link account** (the default) approves in your browser and comes back through My Home Assistant. **Link with a code instead** shows a one-time code to approve. |
| Hub | The Thalovant hub whose devices will be able to send requests to this Home Assistant. You can link several hubs; each one is its own entry. |

Either way, the sign-in asks Thalovant for three permissions: read your hubs
(`hubs:read`), and read and create connections (`clients:read`,
`clients:write`). It asks for nothing that can change a hub. Only if you later
turn on announcements does it ask, in a separate approval, for the Intercom
permissions (`intercom:read`, `intercom:send`, and `intercom:urgent` for urgent
announcements): see [Announcements](#announcements-intercom).

Home Assistant holds one API token per Thalovant account. Signing in again, to
link another hub or to re-link one, replaces it: every hub linked with that
account moves to the new token, and the old one is revoked. It does not count
against your plan's API tokens.

### Options

Open the integration and select **Configure**. One form holds every option; the
second form (**Where to play announcements**) appears only when **Play
announcements on this Home Assistant** is on. The source is
`ThalovantOptionsFlow` in `custom_components/thalovant/config_flow.py`; only what
is on (or not the default) is stored, so an entry that never changed an option is
stored as before. A private Christmas link has no options form: its agent is fixed
to Home Assistant's built-in Assist agent (`private_agent_fixed`).

| Option (label in the form) | Key | Default | Effect |
| --- | --- | --- | --- |
| Conversation agent | `agent_id` | Home Assistant's own agent | The agent that answers requests from the hub. It only acts on entities exposed to Assist. A missing agent is refused with `agent_not_found`; a later disappearance raises a Repairs notice. |
| Send announcements | `allow_announcements` | off | Adds `thalovant.announce`, `thalovant.cancel_announcement` and `thalovant.list_speakers` and a disabled-by-default Intercom notify entity. Asks Thalovant for the Intercom permission first; stays off if you decline. |
| Allow urgent announcements | `allow_urgent` | off | Lets an announcement be urgent (it ignores Do Not Disturb and can repeat until acknowledged). Needs **Send announcements** (`urgent_needs_announcements` otherwise) and its own permission. |
| Play announcements on this Home Assistant | `allow_receive` | off | Lets the hub play announcements on the players and areas of the second form, with the text to speech you choose (default: Home Assistant's), at each player's current volume. The second form needs at least one player or area (`receive_needs_players`). |
| Carry out structured requests | `structured_actions` | on | Off: every request goes to Assist as words, as in 0.4.0. Only the off value is stored. |
| Allow locks, alarms, garage doors, gates, valves and sirens | `structured_sensitive` | off | Lets a structured action lock or unlock a lock, arm or disarm an alarm panel, open a garage, gate, door or window cover, open a valve or set its position, and switch a siren. Off: those actions are not carried out structurally and go to Assist as words. Details in [Sensitive actions](#sensitive-actions). |
| Alarm code (to disarm) | `alarm_code` | empty | A password field. Kept in the entry's options, never sent by the hub; passed to the alarm panel's arm and disarm services. An alarm panel is disarmed by a structured action only with it. Redacted from diagnostics. |
| Media players, Areas, Text to speech (second form) | `speaker_players`, `speaker_areas`, `tts_entity` | none | Where the hub's announcements are played, and with which text to speech. Redacted from diagnostics. |

Changing an Intercom option reloads the entry; the structured-request options are
read on every request and need no reload (`_async_options_updated` in
`__init__.py` compares only the Intercom keys).

### Private Christmas hubs

If you run Christmas Protocol on your own HiveMind hub, turn on **Link a
self-hosted Christmas hub** in the first setup screen. Use the private hub's
root `wss://` URL with a certificate trusted by Home Assistant. Enter the access
key, password and numeric connection ID for a dedicated Home Assistant client
issued by the hub operator. Enter the separate numeric ID of the Voice client
allowed to control the mirror's Christmas lighting.

The private listener needs `hivemind-home-router` and one listener replica.
The hub operator must bind the Home Assistant client to the same owner as the
Voice client, give it the `home_assistant` connection kind and grant only
`thalovant.home.response`. The link uses the existing Christmas lighting
receiver in Home Assistant. It accepts the seven Christmas mirror lighting
commands from the configured Voice client and uses the built-in Assist agent.
The host and Voice ID stay fixed when you renew the credentials.

After setup, check that the **Hub connection** sensor is on. The integration
stores the credentials in its Home Assistant entry and retains the Noise key
under `.storage/thalovant`. Enter the credentials in your trusted Home Assistant
administration session. WSS secures the connection from Home Assistant to the hub.
When removing the private integration entry, ask
your hub operator to revoke its dedicated client. The credentials were issued
by that hub, so its operator manages the link's lifecycle.

See [private link implementation and validation](docs/index.md), the
[Home router contract](https://github.com/thalovant/hivemind-home-router) and
the [Christmas Protocol receiver](https://github.com/thalovant/thalovant-skill-christmas-protocol).

## What you get

- **A device for each linked hub**, listed as a service.
- **A device for each Thalovant device that speaks through it**, created the
  first time it asks something. Give it an area and Assist knows which room
  "turn off the lights" means.
- **Hub connection**, a connectivity sensor on that device. It is on while the
  hub can reach this Home Assistant, and off while the link is down.
- **Diagnostics** you can download from the integration page. They hold
  counts and timings, never a token, a key, or anything that was said or
  announced.
- **Repair notices** when the conversation agent chosen in the options no
  longer exists, when the hub answers with a different security key, and, if
  announcements are on, when Intercom cannot run on the hub (plan, kid or public
  hub, switched off by Thalovant or by the hub's owner).
- **With the options on**, and only then: the announce actions, an Intercom
  notify entity, and playing the hub's announcements.

Updates are pushed: the link stays open and the sensor changes the moment the
connection does. Nothing is polled.

## How it works

1. A Thalovant device (the appliance, the desktop app, or your phone) hears
   "turn off the kitchen light".
2. The home skill on your hub sends the sentence, with its language and the
   device's id and name, to the Home Assistant connection of the account that
   owns the device. The hub takes the id from its own record of the sender,
   never from what the device says about itself.
3. This integration hands it to Assist in that language, along with the
   Home Assistant device that stands for the one that asked.
4. Assist acts and answers. The integration sends the answer back within 10
   seconds, and the hub speaks it.

On `main` (not in 0.4.0), step 3 has a first branch: when the request also carries
a structured `action` and the options leave structured requests on, the
integration resolves it against Home Assistant's registries and calls the
entities' own services, and only goes on to Assist with the sentence when it
cannot resolve it exactly. See [Structured actions](#structured-actions).

If Assist does not understand, cannot find the device, or takes too long, the
hub still gets an answer with a short sentence it can say, in the language of
the request when this integration has a translation for it (English and
French today).

## Examples

Anything Assist understands works. With the built-in agent, for example:

- "Turn off the kitchen light."
- "Is the front door locked?"
- "What is the temperature in the living room?"
- "Allume la lumière du salon."

### Rooms

Say "turn off the lights" with no room, and Assist picks the lights in the area
of the device that heard you, the way it does for a Home Assistant voice
satellite.

1. Ask the device something once, so it shows up.
2. Go to **Settings** > **Devices & services**, open **Thalovant**, and open
   the device under the hub.
3. Set its **Area**.

The device takes the name you gave it in Thalovant; rename it in Home Assistant
and your name is kept. A device with no area behaves as before: Assist has no
room to go on, so name the room in the sentence.

Get told when the link to the hub drops for more than five minutes:

```yaml
automation:
  - alias: "Thalovant hub unreachable"
    triggers:
      - trigger: state
        entity_id: binary_sensor.maison_hub_connection  # your hub's sensor
        to: "off"
        for: "00:05:00"
    actions:
      - action: notify.notify
        data:
          message: "Thalovant can't reach Home Assistant right now."
```

## Announcements (Intercom)

> **Safety notice.** Intercom is a convenience, **not a certified safety
> system**. It does not replace smoke or carbon monoxide alarms, medical alert
> devices or emergency services, and it can fail silently: Home Assistant, your
> internet connection, Thalovant, the hub or a speaker can be down, a speaker can
> be set not to receive, Do Not Disturb can skip an announcement, and nobody may
> be home to hear it.

> **Intercom is rolling out.** Thalovant ships it switched off for everyone and
> turns it on deliberately, so it **may not be enabled on your hub or account
> yet**. While it is off, every announcement is refused by Thalovant with
> "Intercom is rolling out on Thalovant and is not switched on yet. Nothing was
> sent", a notice appears under **Repairs** (nothing is wrong on your side and
> nothing needs fixing), `thalovant.list_speakers` still works and says
> `unavailable_reason: platform`, and `thalovant.cancel_announcement` always works.
> Nothing crashes and nothing is retried. Turning the options on early is safe.

Everything here is **off by default**. It needs Intercom switched on by Thalovant
for the whole platform (the point above), a Thalovant plan that includes
Intercom, a hub that is not a kid or public hub, Intercom switched on for the
hub by its owner or a manager in the Thalovant dashboard (its **Intercom** tab),
and each speaker set to receive there. Announcing needs the Thalovant account
that linked Home Assistant to be an owner or a manager; a plain member can read
but Thalovant refuses their announcements (403). The
[announcements guide](docs/announcements.md) has every field, error and limit.

**Send.** Open the integration, select **Configure**, and turn on **Send
announcements** (and **Allow urgent announcements** if you want them). Thalovant
asks you to approve the extra permission first, the same way you linked; if you
decline, the option stays off. Then:

```yaml
actions:
  - action: thalovant.announce
    data:
      message: "The front door has been open for five minutes."
      target: rooms          # all (default), speakers, rooms or groups
      names: [kitchen, entrance]
```

`message` is 1 to 280 characters (counted after Unicode NFC normalisation and
trimming). Line breaks and tabs become spaces; `<` and `>`, control,
text-direction and other invisible characters, private-use characters and line
or paragraph separators are refused, never silently dropped: it is the
platform's own rule, checked here first so a refusal costs no request.
`priority: urgent` with `repeat_times` (1 to 10) and `repeat_interval` (5 to 120
seconds) repeats until somebody acknowledges it, and needs its own
`intercom:urgent` permission, asked for only when you turn **Allow urgent
announcements** on; `thalovant.cancel_announcement` stops it. At most two urgent
announcements repeat on one hub at a time, and an urgent one needs the Intercom
skill on the hub. `thalovant.list_speakers` returns the speakers, rooms and
groups you can name, with each speaker's `kind` and whether it `can_play` speech
(a connection that cannot is listed but cannot receive and is never part of
every speaker, a room or a group), and `policy_synced: false` while a change may
take a moment to reach the home. The Intercom notify entity (disabled until you enable it) makes a normal
announcement to every speaker from `notify.send_message`. Home Assistant fires
`thalovant_announcement_updated` (the announcement's id and status, never the
text) as an announcement's status changes.

Every call makes a fresh unique idempotency key and **nothing is retried**. After
an error that may have come after the hub spoke (a 502 `hub_unreachable`, or no
answer), the error says that it **may still have been spoken**, with the
announcement's id when Thalovant gave one: look in the dashboard before sending
again. At most 20 normal announcements a minute and 5 urgent ones an hour leave
one linked hub (Thalovant's own limits are 20 and 10, and a 429 from it says how
long to wait, with nothing sent).

**Play.** Turn on **Play announcements on this Home Assistant** and choose media
players and/or areas (and a text to speech, or leave Home Assistant's default).
When the hub makes an announcement, Home Assistant says it on those players with
`tts.speak`, at their current volume (urgent changes no volume), and plays at most
6 new announcements a minute. The hub's owner must also switch **receive** on for
this connection in the dashboard's **Intercom** tab: turning the option on here
tells Thalovant the connection *can* play (`spec.intercom.can_play`, without
which a Home Assistant connection is not a speaker at all), and nothing more.
Delivering the hub's announcements to a Home Assistant link also depends on the
hub's Intercom skill, which is rolling out with the rest.

**A smoke, carbon monoxide or fall sensor.** You may announce from one, but keep
your real alarms. A fall sensor can miss a fall and report one that did not
happen, and an announcement is only heard if a receiving speaker is up, nobody
has muted it, and somebody is home. Use certified alarms, a medical alert device
and emergency services for those.

```yaml
automation:
  - alias: "Kitchen smoke: tell the house"
    triggers:
      - trigger: state
        entity_id: binary_sensor.kitchen_smoke
        to: "on"
    actions:
      - action: thalovant.announce
        data:
          message: "The kitchen smoke detector is going off. Check it now."
          priority: urgent
          repeat_times: 3
          repeat_interval: 20
```

The text goes Home Assistant, Thalovant's API, your hub, then each speaker's text
to speech. Thalovant keeps a keyed hash of it and its length, not the text; this
integration never logs, stores or puts it in an event, a repair, an error or
diagnostics. Home Assistant's own automation traces keep what an automation was
told to say. Intercom does not record or store speech; while an urgent
announcement repeats, the hub only checks whether a reply is an acknowledgement.

## Structured actions

> **Not in a release yet.** This section describes `main` after `v0.4.0` (pull
> requests #30 and #32, and the music actions of #31). `manifest.json` still says
> 0.4.0; the next release is expected to be 0.5.0.

A hub request can carry, next to its sentence, an `action`: a **capability** (what
is wanted), a **target** (which entity or entities) and a **value**, absolute or
relative. The integration resolves the target among the entities **exposed to
Assist** and calls those entities' own Home Assistant services, the way a smart
home skill does, instead of leaving a sentence to Assist's parser. The home skill
sends one for the sentences Assist cannot parse ("dim the lamp", "toggle the
lights", "make it warmer": [thalovant-skill-home: README.md]); the music skill
sends them for Music Assistant. The router checks every action against the
connector spec before it reaches Home Assistant ([hivemind-home-router:
README.md], [thalovant-connector-spec: docs/design.md]); this integration does
its own checks on top and trusts nothing but the closed set of capabilities below.

Source: `custom_components/thalovant/actions.py` (`resolve()`, `async_execute()`,
`CAPABILITY_DOMAINS`, `BUILDERS`) and `HomeRequestHandler._async_structured()` in
`handler.py`.

### What it can do

| Capability | Domains | Service called, and how the value is read |
| --- | --- | --- |
| `power_on`, `power_off` | light, switch, fan, input_boolean, humidifier, media_player, remote, climate, water_heater, automation, cover, valve, siren | `turn_on` / `turn_off`; a cover uses `open_cover` / `close_cover`, a valve `open_valve` / `close_valve` |
| `toggle` | light, switch, fan, input_boolean, cover | the domain's own `toggle` |
| `brightness` | light | `turn_on` with `brightness_pct`. Relative: the light's real brightness (0 when it is off) plus the value, clamped to 1 to 100. Absolute: 0 turns it off |
| `color` | light | `turn_on` with `rgb_color` from a colour name in `value` (a name Home Assistant's colour table does not know is not done) |
| `color_temperature` | light | `turn_on` with `color_temp_kelvin`: a number, or a name: candle light 1900, warm white / warm / soft white 2700, neutral white 3500, cool white / cold white / cool 4000, daylight 6500 |
| `position` | cover, valve | `set_cover_position` / `set_valve_position`, 0 to 100. Relative needs the entity's `current_position` |
| `fan_speed` | fan | `set_percentage`. Relative: the fan's real percentage plus or minus the larger of its own `percentage_step` (25 when it has none) and the value; "slower" never switches a running fan off |
| `temperature` | climate, water_heater | `set_temperature`, rounded to 0.5. Relative: the setpoint plus the value (the measured temperature only when there is no setpoint) |
| `hvac_mode` | climate | `set_hvac_mode` |
| `humidity` | humidifier | `set_humidity`, 0 to 100 |
| `lock`, `unlock` | lock | `lock.lock`, `lock.unlock` (sensitive) |
| `volume` | media_player | `volume_set`. Relative: the real `volume_level` plus value / 100 |
| `mute`, `unmute` | media_player | `volume_mute` |
| `playback` | media_player | `value` is `play`, `pause`, `stop`, `next` or `previous`: `media_play`, `media_pause`, `media_stop`, `media_next_track`, `media_previous_track` |
| `activate` | scene, script, automation, button, input_button | `turn_on` (scene, script), `trigger` (automation), `press` (buttons) |
| `start`, `stop`, `dock` | vacuum (`start`, `stop`, `return_to_base`), lawn_mower (`start_mowing`, `dock`; no `stop`) | the matching service |
| `arm`, `disarm` | alarm_control_panel | `alarm_arm_away` (default), `alarm_arm_home` or `alarm_arm_night` from `value` (`away`, `home`, `night`); `alarm_disarm` (sensitive; needs the alarm code) |
| `state` | any domain named by the target | reads one entity and answers "{name} is {state} {unit}." Several entities are not answered (the first would be said and the rest dropped) |
| `play_media`, `now_playing`, `shuffle`, `repeat`, `transfer`, `join`, `unjoin` | media_player (Music Assistant players) | see [Music](#music) |

A relative value is a change from the entity's real state (the skill's "dim" is
-20 points, "warmer" is +1 degree); an absolute one is the end state. A relative
change that needs a state the entity does not report (a cover with no
`current_position`, a fan with no `percentage`) is not done.

### How a target is resolved

Only entities exposed to Assist (`async_should_expose(hass, "conversation", ...)`)
and only the domains the capability allows (a `domain` in the target narrows them
further). Then, in this order:

- `name`: matched, ignoring case, accents and punctuation, against the entity's
  name, its registry name and its aliases. One match is the target; **two
  entities with the name are not guessed** (the request goes on as words so
  Assist can ask which).
- A `name` that is no entity's, with no area, floor or `here`, is read as an
  **area name**, then as a **floor name** ("make the living room warmer"), when it
  names exactly one.
- `area` and `floor`: matched by name or alias; **a name two areas share ("guest")
  is not a room** and resolves to nothing.
- `here`: the area of the Thalovant device that spoke. That device exists in
  Home Assistant after its first request (see [Rooms](#rooms)); one with no area
  resolves to nothing ("Which room?" is Assist's to ask).
- `all` or a bare area/floor: every matching entity, at most **50**. With no
  `domain`, a bare area for `power_on`, `power_off` or `toggle` means the area's
  **lights** only ("turn off the kitchen").
- Anything else (no name, area, floor, `here` or `all`; no match; more than 50)
  resolves to nothing.

### What happens when it cannot, or fails

The integration never guesses. It does **nothing structurally** and the request
goes on as the sentence it carries, through the configured conversation agent,
when: the capability is unknown; the target resolves to nothing, to two entities,
or to an entity the domain cannot do; a service the action needs is not
registered; a relative value needs a state that is missing; the option is off; or
the action is sensitive and sensitive actions are off. If one of several entities
cannot be done, none is touched.

A request is **never** structured, whatever it carries, when it is a follow-up to
Assist's own question (it has a `conversation_id`), or when the link is a private
Christmas link.

| Outcome | What the hub is told | Spoken (English; French has its own, other languages hear English) |
| --- | --- | --- |
| Done | `action_done` | "Done." (the entity's name is available as a placeholder; the shipped line does not use it) |
| A state read | `query_answer` | "{name} is {state}." |
| A service failed before anything changed | none: the sentence goes on to Assist | Assist's own answer |
| A service failed after part was done | `error`, `failed_to_handle` | "Sorry, I could only do part of that." The sentence is **not** sent to Assist, because that would run the intent again on everything, doubling a relative step and undoing a toggle |
| Out of time (the request's budget is shared with Assist; at most 8.5 s of the hub's 10) with nothing changed | `error`, `timeout` | "Sorry, Home Assistant took too long to answer." |
| Out of time after part was done | `error`, `failed_to_handle` | "Sorry, I could only do part of that." |
| The resolver crashed | none: the sentence goes on to Assist (a warning with the exception type is logged) | Assist's own answer |

Services are called with a fresh Home Assistant `Context`, no user, one call per
entity, waiting for each. Nothing is retried.

### Sensitive actions

A **sensitive** action is one a person should not trigger by voice without the
household having decided so. The hub-side contract flags the four verbs `lock`,
`unlock`, `arm` and `disarm` `sensitive` in the connector spec
([thalovant-connector-spec: connectors/home_assistant.json], rate bucket
`sensitive_per_minute` 6); this integration keeps the same four in
`SENSITIVE_VERBS`, and `tests/test_sensitive_verbs.py` fails if the two differ
(it skips when the private spec package is not installed, which is the case in
this repository's CI: see AUDIT.md). The integration also treats as sensitive,
whatever the verb:

| Entity | Sensitive when the action is |
| --- | --- |
| any entity | `lock`, `unlock`, `arm`, `disarm` |
| siren | `power_on`, `power_off`, `toggle` (both directions) |
| valve | `power_on` (open), `position` |
| cover with device class `garage`, `gate`, `door` or `window` | `power_on` (open), `position`, `toggle` (closing a garage is **not** sensitive) |

What a sensitive action requires, all together:

1. **The option is on**: *Allow locks, alarms, garage doors, gates, valves and
   sirens* (`structured_sensitive`, off by default). Off, nothing structural is
   done and the sentence goes to Assist, where Home Assistant's own exposure rules
   decide (locks are not exposed to Assist by default).
2. **The entity is exposed to Assist**, like every other target.
3. **Exactly one entity.** "Unlock the kitchen", `all` on locks, or a floor name
   never spreads over several: it goes to Assist as words. The same rule applies
   to **runnable** domains (scene, script, automation, button, input_button):
   "turn off all the automations" or "run all the scripts" is never done
   structurally, one named entity at a time.
4. **For `disarm`, the alarm code** set in the options. Without it, no `disarm`
   is built and the sentence goes to Assist. `arm` works without a code (it passes
   the code when one is set); the mode is `away` unless the value says `home` or
   `night`.

The alarm code is stored **in clear** in the config entry's options, like any
integration's secret in Home Assistant's `.storage`; it is never sent by the hub
(the request has no field for it), it travels in the `alarm_control_panel`
service data (which Home Assistant's event bus shows to administrators), and it
is **redacted from diagnostics** (see [Diagnostics](#diagnostics)). The home
skill never builds `lock`, `unlock`, `arm` or `disarm` today
([thalovant-skill-home: README.md]), so these paths are reached only by other
clients of the router.

### What is not done structurally

Timers, to-do and shopping lists (their own Thalovant skills); cameras, sensors
(other than a `state` read), `person`, `device_tracker`; `input_number`,
`input_select`, `number`, `select` and `text` values; a siren's tone or volume;
water heater operation modes; remote commands (only power). `input_boolean`
(power, toggle), `remote` (power) and `input_button` (press) **are** carried out.

### Verification

`tests/test_actions.py`, `test_actions_edges.py` and `test_structured_handler.py`
run the resolver and the handler on Home Assistant 2026.10.4's test harness with
registry fixtures (areas, floors, aliases, exposed and unexposed entities, mocked
services). The README of the home skill records a demo-integration check of the
resolver. **Not verified**: a live hub, the router and this integration together
on real entities, and any device other than the fixtures.

### Music

The same link plays and steers your **Music Assistant** players (the *Music Assistant* integration of Home Assistant): play a track, album, artist, playlist or radio by name, queue next or last, favorites, more like this, shuffle, repeat, move or group rooms, what is playing, plus volume and playback. The players must be exposed to Assist; nothing new is opened and no Music Assistant token leaves your Home Assistant. See [docs/music.md](docs/music.md) ([en francais](docs/music.fr.md)); limits (genre play, adding to favorites) are listed there.

## What it cannot do

- It only controls what you have exposed to Assist. If Assist cannot do it by
  voice from Home Assistant's own dialog, it cannot do it from Thalovant either.
- It does not turn Home Assistant into a Thalovant satellite. Home Assistant
  never sends what it hears to the hub; it only answers. With announcements on it
  also sends the text you tell it to announce, and with playing on it says the
  hub's announcements on your media players.
- One link per hub for each Thalovant account. A second Home Assistant on the
  same hub and account is refused until you remove the first link.
- The hub waits 10 seconds for an answer, counted from when it asked. A slow
  agent (a large language model, for example) gets 8.5 of them and is then cut
  off; an answer that would arrive after the hub gave up is not sent at all.
- The language comes from the request. An agent that does not speak it
  answers with an error.
- Moving a link to another hub means removing the entry and adding a new one.

## Privacy

- **What is stored.** The Thalovant API token from the sign-in (valid for a
  year, one per account, the same whichever way you linked) and the
  connection's keys, in Home Assistant's config
  entry storage, like any other integration's credentials. The key the hub
  recognises this Home Assistant by, and the hub's own key, live in
  `.storage/thalovant/`, one folder per link, so they survive updates and are
  part of your backups.
- **What leaves your home.** Only Assist's answers, sent to your hub, and,
  only if you turn announcements on, the text of each announcement you send
  (see [Announcements](#announcements-intercom)). No Home Assistant token, and no
  entity list.
- **Logs.** This integration never logs what was said, what Assist answered or
  what was announced, even at debug level; it logs request ids, outcomes,
  announcement ids, error types and timings. Home
  Assistant's own `conversation` integration does log the sentence when *its*
  debug logging is turned on.
- **Diagnostics** redact the tokens, the connection keys, the account id, the
  hub's name and the players, areas and text to speech chosen for announcements.

## Troubleshooting

**The sign-in code expired or was declined.** Select **Submit** again for a
new code.

**"My Home Assistant, which is not turned on in this Home Assistant".**
**Link account** needs My Home Assistant to bring the approval back. Add `my:`
to `configuration.yaml` (or keep `default_config:`) and restart, or select
**Submit** to link with a code.

**"Thalovant did not accept the approval because it came from a different
network".** Thalovant refuses an approval given from another network than
Home Assistant's, for example over mobile data, a VPN or remote access. From a
phone or computer on Home Assistant's network, select **Submit** to link again.

**"Thalovant did not accept the approval: it had expired … or was already
used".** An approval is good for one minute and only once. Select **Submit** to
try again.

**"Invalid state. Is My Home Assistant configured to go to the right
instance?"** If Home Assistant restarted during the sign-in, start a new link:
a restart forgets the one in progress. If the error persists, My Home Assistant
is sending your browser to another Home Assistant: open
[My Home Assistant][my] and check that the address it remembers is this
Home Assistant's.

**"This hub can't link Home Assistant yet".** The hub or the Thalovant API
does not support Home Assistant connections yet. Pick another hub; there is
nothing to fix on your side.

**"Your Thalovant plan links Home Assistant to public hubs only".** On the
Free plan, pick a public hub such as Daily Desk, or upgrade.

**"Your Thalovant plan has no room for another link".** Remove one in the
[Thalovant dashboard][dashboard], then try again.

**"Thalovant refused to create the connection".** Something else went wrong
on the Thalovant side. Try again later; the log has the API's reason.

**"Another Home Assistant is already linked to this hub".** Remove the old
link under **Connections** in the Thalovant dashboard.

**The hub took too long to admit Home Assistant.** The connection that was
being set up is deleted, so trying again starts clean. Wait a few minutes
first.

**"Retrying setup" right after linking.** The hub can take a few minutes to
accept a new connection. Home Assistant keeps trying on its own; for the first
ten minutes a refusal is treated as "not admitted yet", not as bad
credentials.

**Home Assistant asks you to reauthenticate.** The hub rejected the
connection's keys, for example because the connection was deleted from the
dashboard. Follow the notification: the integration makes a new connection,
and only asks you to sign in again (with **Link account** or a code, as you
choose) if the stored token no longer works.

**"answered with a different security key" in Repairs.** The hub presented a
different key than the one it had when you linked it. Home Assistant stops
talking to it and asks you to re-authenticate. Do that only if you know the
hub was replaced or reset: re-linking makes a new connection and trusts the
key the hub presents now.

**"no longer recognizes this Home Assistant" in Repairs.** The hub refused
the key Home Assistant uses for the link: it remembers the one Home Assistant
had when you linked it, and this one is different. Home Assistant usually
lost its key, for example after restoring a partial backup without the
`.storage/thalovant` folder. Follow the request to re-authenticate: re-linking
makes a new connection with a new key.

**The hub says Home Assistant didn't understand.** Try the same sentence in
Assist in Home Assistant. If it fails there too, the entity is probably not
exposed to Assist, or its name differs from what you said.

**A device says "I'm not connected to your home yet".** The hub has no Home
Assistant link for the account that device is signed in to. Link it here with
the same Thalovant account. The [guide][guide] lists every sentence a device
can say and what to do about it.

**Turning on announcements opens a re-authentication request.** Thalovant needs
your approval for the Intercom permission before the option is saved. Open it
from the notification or **Repairs**, approve it, and the options are stored. If
you decline, or Thalovant does not grant it (your plan may not include Intercom),
nothing is turned on.

**"Announcements are turned off for ..." when calling `thalovant.announce`.**
Turn on **Send announcements** in the integration's options. With more than one
hub linked and announcements on for several, name one with `config_entry_id`.

**"Intercom is rolling out on Thalovant and is not switched on yet" (an error,
and a notice in Repairs).** Nothing is wrong on your side. Thalovant ships
Intercom switched off and turns it on deliberately; until then every announcement
is refused and nothing is sent. Home Assistant checks again when it starts, and
when you try to announce. You can leave the options on.

**"Intercom is off for ..." (or "not part of the plan", "kid hub", "public hub")
in Repairs.** Intercom cannot run on the hub. The notice says why: the hub's owner
switches it on in the dashboard, a plan with Intercom is needed, and kid and
public hubs never have it.

**Urgent announcements are refused.** "The permission for urgent announcements"
means the token lacks `intercom:urgent`: turn **Allow urgent announcements** off
and on again to approve it (the plan must include it). "Already has the most
urgent announcements it allows repeating" (2 on a hub): stop one with
`thalovant.cancel_announcement` or wait. "The Intercom skill is not installed on
the hub yet": switch Intercom on for the hub in the dashboard and wait for the
skill to install. Nothing was sent in any of these.

**"A speaker you named cannot play speech".** That connection is listed but is
not a speaker (a Home Assistant link plays announcements only once it is set up
to, and its owner has switched receiving on). `thalovant.list_speakers` shows
`can_play` for each. **"More than 50 speakers"**: name a room or a group, or fewer
speakers.

**"It may still have been spoken".** Thalovant could not confirm the
announcement. Check the Thalovant dashboard before sending it again; Home
Assistant does not retry.

**Announcements from the hub are not played.** Check that **Play announcements
on this Home Assistant** is on with at least one available media player or area,
that a text to speech exists, that the hub's owner switched **receive** on for
this connection in the dashboard, and that Repairs shows no "was not told that ...
can play announcements" notice. Diagnostics list what was ignored and why.

**Debug logs.** Add this to `configuration.yaml` and restart:

```yaml
logger:
  logs:
    custom_components.thalovant: debug
    thalovant: debug
```

## Removing the integration

1. Go to **Settings** > **Devices & services**, open **Thalovant**, and
   delete each entry. Deleting an entry also deletes its connection on the
   hub, and deleting the last entry of an account revokes the API token. If
   Thalovant cannot be reached at that moment, the log says so; remove them
   from the [Thalovant dashboard][dashboard] instead.
2. To remove the code too, open **HACS**, find **Thalovant**, and select
   **Remove**, then restart Home Assistant.

## Development

```sh
python3.14 -m venv .venv
.venv/bin/pip install -r requirements_test.txt -r requirements_lint.txt
# The SDK, under Home Assistant's own package constraints, the way Home
# Assistant installs an integration's requirements.
constraints="$(.venv/bin/python -c 'import homeassistant, pathlib; print(pathlib.Path(homeassistant.__file__).parent / "package_constraints.txt")')"
.venv/bin/pip install -c "$constraints" thalovant==0.12.0
.venv/bin/pytest --cov
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy
```

The integration talks to Thalovant through the async API of the `thalovant`
Python SDK (0.12.0 or later, the first with Intercom), and only through
`custom_components/thalovant/api.py` (`oauth.py` keeps its own token exchange).
`tests/test_api.py` drives that adapter with a fake SDK, and
`tests/test_api_sdk.py` drives it with the real one against a local control
plane.

## License

[Apache License 2.0](LICENSE).

[expose]: https://www.home-assistant.io/voice_control/voice_remote_expose_devices/
[guide]: https://docs.thalovant.com/manage/home-assistant/
[my-hacs]: https://my.home-assistant.io/redirect/hacs_repository/?owner=thalovant&repository=ha-thalovant&category=integration
[dashboard]: https://dash.thalovant.com
[my]: https://my.home-assistant.io
