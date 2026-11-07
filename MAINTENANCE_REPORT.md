Last Edit: Codex (GPT-6) - 2026-11-06 - Motive: Record the private Christmas link change and local validation.

# Maintenance report

## 2026-11-06 · 0.2.3 candidate

Added a private link flow for Christmas Protocol on an operator-managed hub.
The flow takes separate Voice and Home Assistant IDs and operator-issued
credentials. It uses the existing SDK, hub connection sensor and Assist
handler. The handler checks the Home router's source, request session and
authenticated speaker before calling built-in Assist. The private flow has
its own transport session and keeps its Noise state separate from account links.

The local upstream suite passed 315 tests with 100% statement and branch
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
  TLS and redirect regression tests.
- **Oversight:** Separate agent review of the transport boundary and a root
  review before any release or deployment. The user authorized pairing their
  private Christmas hub and testing the strip.
