Last Edit: Codex (GPT-6) - 2026-11-06 - Motive: Document the routed Christmas request correction.

# Maintenance report

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
