Last Edit: Codex (GPT-6) - 2026-11-06 - Motive: Index account linking and private Christmas lighting contracts.

# Thalovant for Home Assistant

The integration receives home requests from a Thalovant hub and passes them
to Assist. See the [setup guide](../README.md) and [configuration facts](../QUICK_FACTS.md).

| Area | Source |
| --- | --- |
| Pairing | [`ThalovantConfigFlow.async_step_user()` and `async_step_self_hosted()`](../custom_components/thalovant/config_flow.py) |
| SDK transport | [`HubConnection`](../custom_components/thalovant/api.py) and [`async_create_session()`](../custom_components/thalovant/self_hosted.py) |
| Private request validation | [`permits_lighting_request()`](../custom_components/thalovant/self_hosted.py) |
| Assist handoff | [`HomeRequestHandler.async_answer()` and `_async_converse()`](../custom_components/thalovant/handler.py) |
| Entry lifecycle | [`async_setup_entry()` and `async_remove_entry()`](../custom_components/thalovant/__init__.py) |
| Integration checks | [Config, lifecycle and scope](../tests/test_self_hosted.py), [SDK WSS and TLS](../tests/test_self_hosted_transport.py) |

The [Home router](https://github.com/thalovant/hivemind-home-router) supplies
the authenticated speaking-device ID and routes the reply. The [Christmas
Protocol integration](https://github.com/thalovant/thalovant-skill-christmas-protocol)
provides the mirror lighting commands and Home Assistant receiver.
