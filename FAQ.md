Last Edit: Claude Opus 5.5 - 2026-11-08 - Motive: Link account is accepted only from Home Assistant's network; no relay claims.

# FAQ

**What changed in 0.3.0?** The first step offers **Link account** (the
default) and **Link with a code instead**. Link account approves in the
browser and comes back through My Home Assistant; the code is the device
login of 0.2. See
[`ThalovantConfigFlow._async_start_link_account()`](custom_components/thalovant/config_flow.py).

**What does Link account add over a code?** No code to type, and only the
Home Assistant that started the setup can use the approval: the request is
signed with its own secret, and the code is useless without the PKCE verifier
that Home Assistant keeps. Neither method makes approving somebody else's
request safe, so approve only sign-in requests you started. Thalovant
completes either only when it is approved from the same network as the
Home Assistant that asked, so a link sent to someone on another computer or
network gives them nothing. See [`oauth.py`](custom_components/thalovant/oauth.py).

**Link account says Thalovant did not accept the approval.** Thalovant answers
`invalid_grant` (error `link_wrong_network`) when the approval came from
another network than Home Assistant's, for example over mobile data, a VPN or
remote access, and also when it is more than a minute old or already used. Link
again from a phone or computer on Home Assistant's network. See
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
