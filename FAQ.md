Last Edit: Codex (GPT-6) - 2026-11-06 - Motive: Explain the routed lighting fix for connected hubs.

# FAQ

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
