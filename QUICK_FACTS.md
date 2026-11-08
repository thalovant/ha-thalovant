Last Edit: Claude Opus 5.5 - 2026-11-08 - Motive: 0.3.0, Link account accepted only from Home Assistant's network (API #502).

# Quick facts

| Fact | Value |
| --- | --- |
| Project | `ha-thalovant` |
| Home Assistant integration domain and version | `thalovant`, `0.3.0` |
| SDK requirement | `thalovant==0.10.0` |
| Config entry points | `ThalovantConfigFlow.async_step_user()`, `async_step_self_hosted()`, `async_step_reauth()` |
| Sign-in methods | Link account (default): `AbstractOAuth2FlowHandler` steps `auth` and `creation` with `ThalovantOAuth2Implementation`; Link with a code instead: `async_step_login()` (device login) |
| OAuth client | `thalovant-home-assistant` (public, PKCE S256, no secret), the device login's registered app |
| Authorize URL | `https://dash.thalovant.com/authorize` |
| Token exchange | `POST https://api.thalovant.com/v1/auth/native/token`, JSON `{code, code_verifier, client_id, redirect_uri}` |
| Redirect | `https://my.home-assistant.io/redirect/oauth` only; without My Home Assistant the flow offers a code (`async_step_no_my_home_assistant()`) |
| Scopes asked | `hubs:read clients:read clients:write` |
| Approval network | Either sign-in completes only when approved from Home Assistant's own network; for Link account, an exchange from another network gets 400 `invalid_grant` with code `exchange_network_mismatch` (error `link_wrong_network`); any other `invalid_grant` is `link_failed` |
| Entry data | Unchanged since 0.2 (`VERSION` 1, `MINOR_VERSION` 1): either sign-in stores the same `tokens` form |
| Runtime entry points | `async_setup_entry()`, `async_unload_entry()`, `async_remove_entry()` |
| Private request scope | One authenticated Voice ID and the seven Christmas mirror lighting commands, handled by built-in Assist |
| Private transport | TLS-verified WSS and persistent per-link Noise state |

Implementation links and tests are indexed in [documentation](docs/index.md).
