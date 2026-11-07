Last Edit: Codex (GPT-6) - 2026-11-06 - Motive: Verify router provenance on actual SDK delivery.

# Audit

The account sign-in flow obtains its hub list from the Thalovant control plane.
That list cannot enroll an operator-managed hub with no control-plane record.
[`ThalovantConfigFlow.async_step_self_hosted()`](custom_components/thalovant/config_flow.py)
provides a separate configuration entry with no account token. Renewal keeps
the selected hub and Voice ID. The hub operator revokes its client when the
link is removed. [Config and lifecycle tests](tests/test_self_hosted.py).

The private handler validates the exact router source, correlated session,
authenticated Voice ID and lighting phrase before Assist. It uses the built-in
agent for the bounded request set. The transport pins the selected WSS endpoint,
checks TLS, rejects redirects and uses the SDK's persistent Noise identity.
[Request boundary](custom_components/thalovant/self_hosted.py),
[transport regressions](tests/test_self_hosted_transport.py).

Version 0.2.3 dropped routed requests because the SDK's local event identifies
the receiving node as the source. The same serialized request produces no reply
on 0.2.3 and an exact Assist receipt on 0.2.4. The fixed integration checks the
original context from the authenticated connection and denies events with a
forged source or missing original context. The SDK retains the router
destination and correlated session on the reply.
[Routed request regression](tests/test_self_hosted_transport.py).

Local validation passed 317 tests with 100% statement and branch coverage.
The Home Assistant 2026.11.0 smoke used actual SDK receive and reply framing,
the device registry and built-in Assist with an in-memory transport.
Live hub admission, the physical mirror and restoration are separate acceptance
checks for the deployment.
