Last Edit: Codex (GPT-6) - 2026-11-06 - Motive: Record private link boundaries and verification limits.

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

Local validation passed 315 tests with 100% statement and branch coverage.
The Home Assistant 2026.11.0 smoke passed with a real Assist automation and
an in-memory hub connection.
Live hub admission, the physical mirror and restoration are separate acceptance
checks for the deployment.
