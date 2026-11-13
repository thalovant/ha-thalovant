Last Edit: Claude Sonnet 5.5 - 2026-11-12 - Motive: 0.4.0, Intercom: announcements from Home Assistant and playing the hub's announcements, both off by default; aligned with the released `thalovant` 0.12.0 SDK and the final platform API; says plainly that Intercom is rolling out and may not be enabled yet.

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

Open the integration and select **Configure**.

| Option | What it means |
| --- | --- |
| Conversation agent | The agent that answers requests from the hub. The default is Home Assistant's own agent, which only acts on entities exposed to Assist. |
| Send announcements | Off by default. Adds the `thalovant.announce`, `thalovant.cancel_announcement` and `thalovant.list_speakers` actions and a disabled-by-default Intercom notify entity. Asks Thalovant for the Intercom permission first; stays off if you decline. |
| Allow urgent announcements | Off by default, separate. Lets an announcement be urgent (it ignores Do Not Disturb and can repeat until acknowledged). Asks for its own permission. |
| Play announcements on this Home Assistant | Off by default. Lets the hub play announcements on the media players and areas you choose, with the text to speech you choose (default: Home Assistant's), at each player's current volume. |

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

A hub request can carry, next to the sentence, an `action`: a capability (power, brightness, color, color temperature, position, fan speed, temperature, HVAC mode, humidity, lock, volume, mute, playback, activate, start/stop/dock, arm/disarm, state), a target (name, area, floor, domain, or the speaking device's own room) and a value, absolute or relative. The integration resolves it among the entities **exposed to Assist** (names, aliases, areas, floors, domains) and calls the entity's own services: "dim the kitchen lamp" lowers its brightness by a step from its real state, "toggle", "make it warmer" (setpoint plus one), "turn the fan up" (the fan's own step), scenes, scripts, vacuums, media players by name; music (below).

It never guesses. If the action names no exposed entity, two entities share the name, the domain lacks the capability, or a service fails, the request goes on as the sentence it carries, through Assist, exactly as before. A follow-up to Assist's own question is always the sentence.

Options (Settings, Devices & services, Thalovant, Configure):

| Option | Default | Meaning |
|---|---|---|
| Carry out structured requests | on | Off sends every request to Assist as words, as before 0.5. |
| Allow locks, alarms, garage doors, gates, valves and sirens | off | Sensitive actions are only done structurally when on; otherwise they go to Assist as words, where Home Assistant's own exposure rules decide (locks are not exposed by default). |
| Alarm code | empty | Kept in the options, never sent by the hub; an alarm panel is disarmed by voice only with it. |

Not done structurally: timers, to-do and shopping lists (their own Thalovant skills), cameras, `input_*`, `number`/`select`/`text` values, remotes, sirens' tones, water heater modes.

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
