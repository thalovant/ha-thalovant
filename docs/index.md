Last Edit: Claude Opus 5.5 - 2026-11-08 - Motive: Index Link account, the OAuth 2 sign-in through My Home Assistant.

# Thalovant for Home Assistant

The integration receives home requests from a Thalovant hub and passes them
to Assist. See the [setup guide](../README.md) and [configuration facts](../QUICK_FACTS.md).

| Area | Source |
| --- | --- |
| Pairing | [`ThalovantConfigFlow.async_step_user()` and `async_step_self_hosted()`](../custom_components/thalovant/config_flow.py) |
| Link account (OAuth 2 with PKCE) | [`ThalovantOAuth2Implementation` and `tokens_from_answer()`](../custom_components/thalovant/oauth.py); [`ThalovantConfigFlow._async_start_link_account()`, `async_step_creation()`, `async_step_authorize_rejected()` and `async_step_no_my_home_assistant()`](../custom_components/thalovant/config_flow.py) |
| Link with a code (device login) | [`ThalovantConfigFlow.async_step_login()`](../custom_components/thalovant/config_flow.py) and [`ThalovantAuth`](../custom_components/thalovant/api.py) |
| SDK transport | [`HubConnection`](../custom_components/thalovant/api.py) and [`async_create_session()`](../custom_components/thalovant/self_hosted.py) |
| Private request validation | [`permits_lighting_request()`](../custom_components/thalovant/self_hosted.py) |
| Assist handoff | [`HomeRequestHandler.async_answer()` and `_async_converse()`](../custom_components/thalovant/handler.py) |
| Entry lifecycle | [`async_setup_entry()` and `async_remove_entry()`](../custom_components/thalovant/__init__.py) |
| Integration checks | [Config, lifecycle and scope](../tests/test_self_hosted.py), [SDK WSS and TLS](../tests/test_self_hosted_transport.py), [Link account flow](../tests/test_link_account.py), [authorize URL and JSON exchange](../tests/test_oauth.py), [device login flow](../tests/test_config_flow.py) |

## Link account

Link account is Home Assistant's own OAuth 2 flow
(`homeassistant.helpers.config_entry_oauth2_flow`). `ThalovantConfigFlow`
subclasses `AbstractOAuth2FlowHandler`, and each attempt registers a new
`ThalovantOAuth2Implementation` (a `LocalOAuth2ImplementationWithPkce`, so a
new verifier) and picks it by name. Home Assistant signs the `state` with its
own secret, and its `OAuth2AuthorizeCallbackView` resumes the flow when My
Home Assistant brings the browser back. The implementation posts the code
exchange as JSON; `async_step_creation()` turns the answer into the same
`Tokens` a device login gives, and the flow continues at `async_step_account()`
exactly as it does after a code.

The API side (client `thalovant-home-assistant`, the consent page and
`/v1/auth/native/token`) is described in the Thalovant API and the browser
sign-in contract the Thalovant SDKs share.

The [Home router](https://github.com/thalovant/hivemind-home-router) supplies
the authenticated speaking-device ID and routes the reply. The [Christmas
Protocol integration](https://github.com/thalovant/thalovant-skill-christmas-protocol)
provides the mirror lighting commands and Home Assistant receiver.
