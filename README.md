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

> [!IMPORTANT]
> The hub side is still being built. Until your hub runs the Thalovant home
> skill and can create Home Assistant connections, pairing stops with "This hub
> cannot link Home Assistant yet".

## Requirements

- Home Assistant 2026.9 or later.
- [HACS](https://hacs.xyz).
- A Thalovant account with at least one hub. On the Free plan, Home Assistant
  can only be linked to a public hub.

## Installation

### With HACS

1. In Home Assistant, open **HACS**.
2. Open the menu (three dots, top right) and choose **Custom repositories**.
3. Enter `https://github.com/thalovant/ha-thalovant`, choose the type
   **Integration**, and select **Add**.
4. Search for **Thalovant**, open it, and select **Download**.
5. Restart Home Assistant.

### By hand

Copy `custom_components/thalovant` from this repository into the
`custom_components` folder of your Home Assistant configuration, then restart
Home Assistant.

## Linking your hub

1. Go to **Settings** > **Devices & services**, select **Add integration**, and
   choose **Thalovant**.
2. Select **Submit**. Home Assistant shows a link and a code.
3. Open the link, sign in to Thalovant, and approve. The dialog in Home
   Assistant moves on by itself.
4. Pick the hub whose devices should reach this Home Assistant.
5. Wait while the hub admits Home Assistant. It usually takes about a minute
   and a half. The integration is added once the hub is ready.

### What the setup asks for

| Field | What it means |
| --- | --- |
| Hub | The Thalovant hub whose devices will be able to send requests to this Home Assistant. You can link several hubs; each one is its own entry. |

The sign-in asks Thalovant for three permissions: read your hubs
(`hubs:read`), and read and create connections (`clients:read`,
`clients:write`). It asks for nothing that can change a hub.

### Options

Open the integration and select **Configure**.

| Option | What it means |
| --- | --- |
| Conversation agent | The agent that answers requests from the hub. The default is Home Assistant's own agent, which only acts on entities exposed to Assist. |

## What you get

- **A device for each linked hub**, listed as a service.
- **Hub connection**, a connectivity sensor on that device. It is on while the
  hub can reach this Home Assistant, and off while the link is down.
- **Diagnostics** you can download from the integration page. They hold
  counts and timings, never a token, a key, or anything that was said.
- **Repair notices** when the conversation agent chosen in the options no
  longer exists, and when the hub answers with a different security key.

Updates are pushed: the link stays open and the sensor changes the moment the
connection does. Nothing is polled.

## How it works

1. A Thalovant device (the appliance, the desktop app, or your phone) hears
   "turn off the kitchen light".
2. The home skill on your hub sends the sentence, with its language, to the
   Home Assistant connection of the account that owns the device.
3. This integration hands it to Assist in that language.
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

## What it cannot do

- It only controls what you have exposed to Assist. If Assist cannot do it by
  voice from Home Assistant's own dialog, it cannot do it from Thalovant either.
- It does not turn Home Assistant into a Thalovant satellite. Home Assistant
  never sends a sentence to the hub; it only answers.
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
  year) and the connection's keys, in Home Assistant's config entry storage,
  like any other integration's credentials. The key the hub recognises this
  Home Assistant by, and the hub's own key, live in `.storage/thalovant/`, one
  folder per link, so they survive updates and are part of your backups.
- **What leaves your home.** Only Assist's answers, sent to your hub. No
  Home Assistant token, and no entity list.
- **Logs.** This integration never logs what was said or what Assist answered,
  even at debug level; it logs request ids, outcomes, and timings. Home
  Assistant's own `conversation` integration does log the sentence when *its*
  debug logging is turned on.
- **Diagnostics** redact the tokens, the connection keys, the account id, and
  the hub's name.

## Troubleshooting

**The sign-in code expired or was declined.** Select **Submit** again for a
new code.

**"This hub cannot link Home Assistant yet".** The hub or the Thalovant API
does not support Home Assistant connections yet. Nothing to fix on your side.

**"Your Thalovant plan links Home Assistant to public hubs only".** On the
Free plan, pick a public hub such as Daily Desk, or upgrade.

**"Your Thalovant plan already uses all of its connections".** Remove one in
the [Thalovant dashboard][dashboard], then try again.

**"Thalovant refused to create the connection".** Something else went wrong
on the Thalovant side. Try again later; the log has the API's reason.

**"Another Home Assistant is already linked to this hub".** Remove the old
link in the Thalovant dashboard.

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
and only asks you to sign in again if the stored token no longer works.

**"answered with a different security key" in Repairs.** The hub presented a
different key than the one it had when you linked it. Home Assistant stops
talking to it and asks you to re-authenticate. Do that only if you know the
hub was replaced or reset: re-linking makes a new connection and trusts the
key the hub presents now.

**The hub says Home Assistant didn't understand.** Try the same sentence in
Assist in Home Assistant. If it fails there too, the entity is probably not
exposed to Assist, or its name differs from what you said.

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
   hub and revokes the API token it signed in with. If Thalovant cannot be
   reached at that moment, the log says so; remove them from the
   [Thalovant dashboard][dashboard] instead.
2. To remove the code too, open **HACS**, find **Thalovant**, and select
   **Remove**, then restart Home Assistant.

## Development

```sh
python3.14 -m venv .venv
.venv/bin/pip install -r requirements_test.txt -r requirements_lint.txt
# The SDK, under Home Assistant's own package constraints, the way Home
# Assistant installs an integration's requirements.
constraints="$(.venv/bin/python -c 'import homeassistant, pathlib; print(pathlib.Path(homeassistant.__file__).parent / "package_constraints.txt")')"
.venv/bin/pip install -c "$constraints" \
    "thalovant @ git+https://github.com/thalovant/thalovant-python-sdk@8fb35b1"
.venv/bin/pytest --cov
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy
```

The integration talks to Thalovant through the async API of the `thalovant`
Python SDK, and only through `custom_components/thalovant/api.py`.
`tests/test_api.py` drives that adapter with a fake SDK, and
`tests/test_api_sdk.py` drives it with the real one against a local control
plane.

## License

[Apache License 2.0](LICENSE).

[expose]: https://www.home-assistant.io/voice_control/voice_remote_expose_devices/
[dashboard]: https://dash.thalovant.com
