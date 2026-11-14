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

This integration links your Home Assistant to your Thalovant hub. The hub passes
what you said to Home Assistant, Assist handles it, and the hub speaks Assist's
answer on the device that asked.

## Get started

You need Home Assistant 2026.9 or later, [HACS](https://hacs.xyz), and a Thalovant
account with at least one hub.

1. In HACS, search for **Thalovant**, select **Download**, and restart Home Assistant.
2. In **Settings, Devices & services**, add **Thalovant** and choose **Link account**.
3. Expose the entities you want to control to Assist, then try a request on a Thalovant device.

The step-by-step guide with pictures of the screens is [Connect Home Assistant to Thalovant](docs/connect-home-assistant.md);
the [Link Home Assistant page](https://docs.thalovant.com/manage/home-assistant/) covers the same steps. To install by hand, copy `custom_components/thalovant` into your
Home Assistant `custom_components` folder.

## What it does

- **Nothing to open.** Home Assistant connects out to the hub: no port forwarding,
  and no Home Assistant token leaves your home.
- **Assist decides.** Only entities you have exposed to Assist can be controlled.
- **Lights, climate, covers, locks and more** by name, room or floor, and your
  Music Assistant players by voice. Locks, alarms and garage doors are off by
  default for structured requests; the options cover those only. Assist's own
  exposure settings decide the rest, so expose them to Assist only if you want
  voice control of them.
- **Optional announcements** to your hub's speakers and from the hub to your
  Home Assistant media players, only if you turn them on.

## Learn more

[Play music from Music Assistant](docs/play-music-from-music-assistant.md) · [Full guide](docs/guide.md) (linking, options, announcements, structured actions,
troubleshooting, removal) · [Music](docs/music.md) · [Announcements](docs/announcements.md) ·
[Changelog](CHANGELOG.md) · [FAQ](FAQ.md) · [Thalovant documentation](https://docs.thalovant.com/)

## Credits

Created and maintained by [Thalovant contributors](https://github.com/thalovant/ha-thalovant/graphs/contributors),
using [Home Assistant](https://www.home-assistant.io/) and the Thalovant Python SDK.

[Apache License 2.0](LICENSE).
