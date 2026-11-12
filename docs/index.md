Last Edit: Claude Sonnet 5.5 - 2026-11-12 - Motive: 0.4.0, Intercom: announcements and playing, with the guide and where it lives in the code; Intercom is rolling out (the platform switch ships off) and the integration is aligned with the released thalovant 0.12.0 SDK.

# Thalovant for Home Assistant

The integration receives home requests from a Thalovant hub and passes them
to Assist. See the [setup guide](../README.md) and [configuration facts](../QUICK_FACTS.md).
Since 0.4.0, and only when its options turn it on, it also sends announcements to
your hub's speakers and plays the hub's announcements on media players: see the
[announcements guide](announcements.md). Intercom is rolling out on Thalovant and
may not be enabled on your hub or account yet; until it is, the actions say so and
send nothing. Intercom is a convenience, not a certified safety system.

| Area | Source |
| --- | --- |
| Pairing | [`ThalovantConfigFlow.async_step_user()` and `async_step_self_hosted()`](../custom_components/thalovant/config_flow.py) |
| Link account (OAuth 2 with PKCE) | [`ThalovantOAuth2Implementation` and `tokens_from_answer()`](../custom_components/thalovant/oauth.py); [`ThalovantConfigFlow._async_start_link_account()`, `async_step_creation()`, `async_step_authorize_rejected()` and `async_step_no_my_home_assistant()`](../custom_components/thalovant/config_flow.py) |
| Link with a code (device login) | [`ThalovantConfigFlow.async_step_login()`](../custom_components/thalovant/config_flow.py) and [`ThalovantAuth`](../custom_components/thalovant/api.py) |
| SDK transport | [`HubConnection`](../custom_components/thalovant/api.py) and [`async_create_session()`](../custom_components/thalovant/self_hosted.py) |
| Private request validation | [`permits_lighting_request()`](../custom_components/thalovant/self_hosted.py) |
| Assist handoff | [`HomeRequestHandler.async_answer()` and `_async_converse()`](../custom_components/thalovant/handler.py) |
| Entry lifecycle | [`async_setup_entry()` and `async_remove_entry()`](../custom_components/thalovant/__init__.py) |
| Announcements: options, re-consent | [`ThalovantOptionsFlow`](../custom_components/thalovant/config_flow.py), [`ThalovantConfigFlow.async_step_intercom_consent()` and `_async_finish_consent()`](../custom_components/thalovant/config_flow.py), [`scopes_for_options()`](../custom_components/thalovant/intercom.py) |
| Announcements: sending | [`IntercomController`](../custom_components/thalovant/intercom.py), [`async_setup_services()`](../custom_components/thalovant/services.py), [`IntercomNotifyEntity`](../custom_components/thalovant/notify.py) |
| Announcements: playing | [`IntercomSpeakerHandler` and `parse_announcement()`](../custom_components/thalovant/speaker.py), [`ThalovantApi.set_connection_can_play()`](../custom_components/thalovant/api.py) |
| Announcements checks | [Rules, controller and errors](../tests/test_intercom.py), [actions](../tests/test_services.py), [notify](../tests/test_notify.py), [playing](../tests/test_speaker.py), [options and re-consent](../tests/test_intercom_options.py), [setup](../tests/test_intercom_setup.py), [adapter against the real SDK](../tests/test_api_intercom_sdk.py) |
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

Thalovant accepts the exchange only from the network that approved it
(thalovant-api #502), as it accepts a code's approval only from the device's
network. My Home Assistant sends the browser to whichever Home Assistant it is
set up for, so the signed state and PKCE alone do not decide who links. The
API's refusal names the cause with the Problem+JSON code
`exchange_network_mismatch` (detail `invalid_grant`), which becomes the error
`link_wrong_network`. Any other `invalid_grant` is `link_failed`: the code
expired or was already used.

The API side (client `thalovant-home-assistant`, the consent page and
`/v1/auth/native/token`) is described in the Thalovant API and the browser
sign-in contract the Thalovant SDKs share.

The [Home router](https://github.com/thalovant/hivemind-home-router) supplies
the authenticated speaking-device ID and routes the reply. The [Christmas
Protocol integration](https://github.com/thalovant/thalovant-skill-christmas-protocol)
provides the mirror lighting commands and Home Assistant receiver.

## Announcements (Intercom)

The [announcements guide](announcements.md) covers the options, the actions, the
notify entity, the event, playing on media players, the errors and their
meaning, automation examples (a door sensor, and a smoke or fall sensor with the
limits stated plainly) and privacy. Its safety notice applies everywhere it is
mentioned: Intercom is a convenience, not a certified safety system, and it does
not replace smoke or carbon monoxide alarms, medical alert devices or emergency
services.

The integration sends an announcement with one request, a fresh idempotency key,
and no retry. Sending needs the SDK's Intercom calls (`thalovant` 0.12.0, released
on PyPI); `[thalovant-python-sdk: docs/guides/intercom.md]` and
`[thalovant-api: docs/intercom.md]` describe the platform side. Thalovant ships
Intercom switched off for the whole platform (reads answer
`unavailable_reason: platform`, writes answer 503 `intercom_disabled_platform`), so
the integration treats "not switched on yet" as a normal state: a clear error, a
Repairs notice, no crash and no retry
(`ThalovantApi._translate_intercom()`, `IntercomController._error()`).
