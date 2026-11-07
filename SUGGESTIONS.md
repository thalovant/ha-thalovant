Last Edit: Codex (GPT-6) - 2026-11-06 - Motive: Record an operator tooling follow-up for private links.

# Suggestions

Private link setup currently requires four connection values from the hub
operator plus the approved Voice ID. If more private hubs use this flow,
consider an operator tool that supplies those values through a secure setup
package. Keep the same WSS origin, separate client identity and command scope
checks. This would reduce manual entry without expanding who can control Assist.
See [`ThalovantConfigFlow.async_step_self_hosted()`](custom_components/thalovant/config_flow.py).
