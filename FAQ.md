Last Edit: Claude Opus 5.5 - 2026-11-08 - Motive: Answer the Link account questions of 0.3.0.

# FAQ

**What changed in 0.3.0?** The first step offers **Link account** (the
default) and **Link with a code instead**. Link account approves in the
browser and comes back through My Home Assistant; the code is the device
login of 0.2. See
[`ThalovantConfigFlow._async_start_link_account()`](custom_components/thalovant/config_flow.py).

**Why is Link account safer than a code?** A code can be sent to somebody
else, who approves it with their account (device-code phishing). Link
account's approval comes back only to the Home Assistant that started it,
signed with its own secret, and the code is useless without the PKCE verifier
that Home Assistant keeps. See [`oauth.py`](custom_components/thalovant/oauth.py).

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
