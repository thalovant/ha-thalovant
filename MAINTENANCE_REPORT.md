Last Edit: Claude Opus 5.5 - 2026-11-08 - Motive: 0.3.0, Link account through My Home Assistant replaces the code as the default sign-in.

# Maintenance report

## 2026-11-08 · 0.3.0

**Link account** is the default sign-in. A device code can be relayed to
somebody else (device-code phishing); Home Assistant's own OAuth 2 flow cannot:
the browser comes back through My Home Assistant to the very instance that
started the flow, Home Assistant signs the `state` with its own secret, and
PKCE makes a code read on the way useless without the verifier, which never
leaves that Home Assistant. **Link with a code instead** keeps the device login
exactly as it was.

- [`ThalovantConfigFlow`](custom_components/thalovant/config_flow.py) now
  subclasses `AbstractOAuth2FlowHandler`. The first step and `reauth_confirm`
  carry a `link_method` choice, `link_account` by default; after a failed code
  the default is the code. `_async_start_link_account()` builds a new
  `ThalovantOAuth2Implementation` per attempt, and when Home Assistant's
  computed redirect is not exactly `https://my.home-assistant.io/redirect/oauth`
  shows `no_my_home_assistant`, whose **Submit** starts the device login.
  Otherwise it registers the implementation (`async_register_implementation`)
  and picks it by name (`async_step_pick_implementation`), which leads to Home
  Assistant's external step `auth`.
- [`ThalovantOAuth2Implementation`](custom_components/thalovant/oauth.py)
  (a `LocalOAuth2ImplementationWithPkce`, client `thalovant-home-assistant`,
  no secret) adds `scope` and `device_name` (at most 120 characters) to the
  authorize URL and posts the exchange to `/v1/auth/native/token` as a JSON
  body of exactly `code`, `code_verifier`, `client_id` and `redirect_uri`.
  400 is `LinkRejectedError` (`link_failed`), 429 and 5xx or no answer are
  `cannot_connect`. There is no refresh token.
- `async_step_creation()` replaces Home Assistant's own step: it drops the
  code, reads the answer with `tokens_from_answer()` (the SDK's leniency for a
  device token), sets the same `_tokens` and `_minted` the device login sets,
  and continues at `async_step_account()`. The token is kept, shared with the
  account's other entries and revoked when unused exactly as before. A decline
  (`error=access_denied`) is `login_denied`; any other error is `link_failed`.
- Entry data, `VERSION` 1 and `MINOR_VERSION` 1 are unchanged, so entries
  linked with a code before 0.3.0 load and renew as they did.
- English and Canadian French copy for the choice, the external step, the
  missing My Home Assistant step and `link_failed`; `strings.json` and
  `translations/en.json` are identical (`cmp`).

Verification, local, Python 3.14.10, Home Assistant 2026.10.4
(`pytest-homeassistant-custom-component==0.13.375`), SDK 0.10.0 installed
under Home Assistant's package constraints as CI does: `pytest --cov
--cov-report=term-missing` passed 370 tests with 100% statement and branch
coverage; `ruff check .`, `ruff format --check .` and `mypy` passed; hassfest
(`ghcr.io/home-assistant/hassfest:latest` run with podman on the branch)
reported 0 invalid integrations. The existing device-login tests pass with
the code chosen explicitly. [`tests/test_oauth.py`](tests/test_oauth.py)
checks the authorize URL's every parameter, the RFC 7636 vector and, on a
local token endpoint over Home Assistant's own client session, the JSON body
and each failure. [`tests/test_link_account.py`](tests/test_link_account.py)
drives the flow, once through Home Assistant's `OAuth2AuthorizeCallbackView`.
Not verified: a real browser, My Home Assistant and the live Thalovant
dashboard and API, and Home Assistant 2026.9.

Transparency Report: AI Model: Claude Opus 5.5. Actions Taken: designed and
wrote the OAuth 2 sign-in, its tests and the English and Canadian French
copy, and updated the README, docs and records. Oversight: the lead agent's
brief for the owner's browser sign-in work; the pull request waits for review,
and nothing was merged, tagged or released.

## 2026-11-08 · 0.2.5

The sign-in step (`wait_for_login` in [strings.json](custom_components/thalovant/strings.json),
[en](custom_components/thalovant/translations/en.json) and
[fr](custom_components/thalovant/translations/fr.json)) now says to open the
link on a phone or computer on the same network as this Home Assistant, with
any VPN off. Thalovant now approves a device sign-in only from the device's own
network (thalovant-api `fix/device-approval-same-network`), so a code sent to
somebody else cannot give them the account. Setting up through remote access
from another network is refused until the browser is on the home network.

`strings.json` and `translations/en.json` stay identical (`cmp`). The copy is
the only change; the flow and its placeholders are unchanged, which
`tests/test_config_flow.py` asserts. The suite and hassfest run in CI (the
local Python 3.14 environment could not be built: the disk quota was full).

Transparency Report: AI Model: Claude Opus 5.5. Actions Taken: wrote the copy
in English and Canadian French. Oversight: the owner's request of 2026-11-08;
released as 0.2.5 on the owner's "deploy all", built like 0.2.4: `git archive --format=zip --prefix=ha-thalovant-0.2.5/ v0.2.5 LICENSE README.md custom_components/thalovant docs hacs.json` (the same command rebuilds 0.2.4's published zip byte for byte) and its SHA256SUMS.

## 2026-11-06 · 0.2.4

Private Christmas admission reads the original context of the routed request.
The SDK rewrites the local event source to the receiving Home Assistant node.
The integration checks the original router source and keeps the SDK event for
routing the reply. The account connection continues to use the SDK's local
event context.

The local suite passed 317 tests with 100% statement and branch coverage.
Home Assistant 2026.11.0 processed a serialized request through SDK 0.10.0
and built-in Assist and returned the exact receipt to the router destination.

## 2026-11-06 · 0.2.3

Added a private link flow for Christmas Protocol on an operator-managed hub.
The flow takes separate Voice and Home Assistant IDs and operator-issued
credentials. It uses the existing SDK, hub connection sensor and Assist
handler. The handler checks the Home router's source, request session and
authenticated speaker before calling built-in Assist. The private flow has
its own transport session and keeps its Noise state separate from account links.

The local upstream suite passed 316 tests with 100% statement and branch
coverage on Home Assistant 2026.10.4 and SDK 0.10.0. Its transport tests used
the real SDK and local HTTP/TLS fixtures. The SDK dependency also resolved
under the Home Assistant 2026.11.0 package constraints.
An isolated Home Assistant 2026.11.0 smoke also loaded the private form,
installed the redirect guard and returned the exact lighting receipt through
a real built-in Assist automation. The test denied a different Voice ID before
Assist and used an in-memory hub connection.

## Transparency report

- **AI model:** Codex, GPT-6.
- **Actions:** Traced the account eligibility response, compared the two hub
  records, implemented the private flow and added authorization, lifecycle,
  TLS and redirect regression tests. Traced the SDK source rewrite and tested
  the corrected receive and reply paths.
- **Oversight:** Separate agent review of the transport boundary and a root
  review before any release or deployment. The user authorized pairing their
  private Christmas hub and testing the strip.
