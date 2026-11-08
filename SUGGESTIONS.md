Last Edit: Claude Opus 5.5 - 2026-11-08 - Motive: Propose moving the Link account exchange into the SDK.

# Suggestions

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
