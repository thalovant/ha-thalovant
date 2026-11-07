Last Edit: Codex (GPT-6) - 2026-11-06 - Motive: Record the private link release and supported entry points.

# Quick facts

| Fact | Value |
| --- | --- |
| Project | `ha-thalovant` |
| Home Assistant integration domain and version | `thalovant`, `0.2.3` |
| SDK requirement | `thalovant==0.10.0` |
| Config entry points | `ThalovantConfigFlow.async_step_user()`, `async_step_self_hosted()`, `async_step_reauth()` |
| Runtime entry points | `async_setup_entry()`, `async_unload_entry()`, `async_remove_entry()` |
| Private request scope | One authenticated Voice ID and the seven Christmas mirror lighting commands, handled by built-in Assist |
| Private transport | TLS-verified WSS and persistent per-link Noise state |

Implementation links and tests are indexed in [documentation](docs/index.md).
