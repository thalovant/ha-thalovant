Last Edit: Claude Opus 5.5 - 2026-11-08 - Motive: link_wrong_network follows the API's exchange_network_mismatch code only.

# Audit

## Link account (0.3.0)

Link account
([`ThalovantConfigFlow._async_start_link_account()`](custom_components/thalovant/config_flow.py#L689),
[`ThalovantOAuth2Implementation`](custom_components/thalovant/oauth.py)) uses Home Assistant's own OAuth 2
machinery. The `state` is a JWT signed with this installation's secret, and
Home Assistant's `OAuth2AuthorizeCallbackView` refuses any other with a 400
and leaves the flow waiting
([`test_link_account_through_the_callback_view`](tests/test_link_account.py#L205)).
The exchange sends the PKCE verifier, whose S256 challenge went out in the
authorize URL ([`test_link_account`](tests/test_link_account.py#L138) checks the pair). The
verifier goes only to Thalovant's token endpoint, in the exchange's JSON body
and never through the browser, and each attempt makes a new one
([`test_each_link_has_its_own_verifier`](tests/test_oauth.py#L153),
[`test_link_account_invalid_grant`](tests/test_link_account.py#L259)). The redirect must be
exactly My Home Assistant's
([`through_my_home_assistant`](custom_components/thalovant/oauth.py#L76)); otherwise the flow offers
the device login instead
([`test_without_my_home_assistant_a_code_is_offered`](tests/test_link_account.py#L355),
[`test_own_address_is_not_enough`](tests/test_link_account.py#L379)).

Finding (API review, 2026-11-08): My Home Assistant forwards the code to
whichever Home Assistant the approving browser is set up for. A signed state
and PKCE only mean that the Home Assistant that started the flow is the one
that can use the code. If somebody sends you their link and you approve it,
the code can reach their Home Assistant, which holds the verifier. Neither
method makes approving somebody else's request safe. Mitigation:
thalovant-api #502 accepts the Home Assistant exchange only from the network
that approved it; from another network it answers 400 with detail
`invalid_grant` and code `exchange_network_mismatch`, and spends the code. A link sent to someone on another computer or network gives
them nothing. The copy says to approve from a phone or computer on Home
Assistant's network, and to approve only requests you started.
Only that code maps to `link_wrong_network`
([`config_flow.py`](custom_components/thalovant/config_flow.py#L232),
[`test_link_account_invalid_grant`](tests/test_link_account.py#L259),
[`test_reauth_link_failure_returns_to_confirm`](tests/test_link_account.py#L484)). Any
other `invalid_grant`, including one with no code from an API before #502, is
`link_failed` (expired or already used), so the flow never names a network it
was not told about. The detail and code are read by
[`_problem()`](custom_components/thalovant/oauth.py#L150). The network check
itself is the API's and is not tested here.

Secrets: the exchange posts JSON
([`oauth.py`](custom_components/thalovant/oauth.py#L116),
[`test_exchange_posts_json`](tests/test_oauth.py#L190) on a local endpoint).
No error message carries the code or the verifier
([`test_exchange_errors`](tests/test_oauth.py#L253)). A refused code logs the HTTP
status and the problem's detail and code only. `async_step_creation()`
drops the code before the exchange
([`config_flow.py`](custom_components/thalovant/config_flow.py#L215)). It also replaces Home Assistant's own
creation step, which would log a token without `expires_in` in full and store
it as an OAuth entry. The token is held like a device login's: `_tokens` and
`_minted` ([`config_flow.py`](custom_components/thalovant/config_flow.py#L254)), revoked when unused
([`test_link_account_no_hubs_revokes_the_token`](tests/test_link_account.py#L401)).

Fixed in review (CodeRabbit on #26): closing the dialog while the exchange
was in flight let the token arrive after `async_remove` had run, so nothing
revoked it. `async_step_creation()` now revokes such a token and aborts
([`config_flow.py`](custom_components/thalovant/config_flow.py#L247),
[`test_closed_while_thalovant_answers`](tests/test_link_account.py#L544)). The same window
exists, from before 0.3.0, for a connection whose creation is in flight when
the dialog closes; it is left as it was.

Known, accepted: the last implementation registered stays in Home Assistant's
implementation registry (`hass.data`) after its flow ends, with its verifier.
The verifier holds no token. It is worthless once its code is spent or past
its 60 seconds, and the next attempt replaces it. There is no public way to
unregister an implementation.

Not verified locally: the Home Assistant frontend opening the tab, My Home
Assistant's redirect, the live dashboard consent page (including how it reads
`scope`, sent as `hubs:read+clients:read+clients:write`, and a `state` of about
200 characters) and the live token endpoint, with #502's network check. The
minimum Home Assistant 2026.9 was not run; the suite ran on 2026.10.4.

## Earlier findings

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
