# ADR-0016: WhatsApp for client notifications, Slack kept for internal ops

- **Status:** Accepted
- **Date:** 2026-09-28

## Context

Approved margin calls are currently posted to Slack. A real counterparty is far more likely to be reached on WhatsApp than in our Slack workspace. GCP has no first-party WhatsApp service, so this is the one non-GCP integration in the plan.

## Decision

- **Client-facing margin-call notices** go out over the **WhatsApp Business Cloud API** (Meta, direct) via a new `whatsapp_notifier` MCP server on Cloud Run.
- Business-initiated messages use a **pre-approved utility template** (`margin_call_notice`) whose variables (amount, currency, deadline, call id) come from calc output — the model does not write the amounts.
- Client replies arrive on a webhook (Cloud Run), published to Pub/Sub, go through Model Armor screening (ADR-0014), and feed the existing respond/dispute path.
- **Slack stays** for internal ops: approval requests, escalations, SLA alerts.
- Notifier interface with `whatsapp` / `slack` adapters; `CLIENT_NOTIFIER=whatsapp|slack`.

## Consequences

- **Cost: $0 for the demo.** Meta's free test number can message up to 5 verified recipients; no business verification or payment needed at this scale.
- Secrets (access token, phone number id, webhook verify token) go in Secret Manager.
- Webhook signature (`X-Hub-Signature-256`) must be verified before any reply is processed.
- Gemini Live voice notifications were considered and rejected (ADR-0009).

## Amendment (2026-10-01): test-account setup findings

**Setup.** Meta app `MarginMaestro-Dev` (`1122045500334789`), test WhatsApp Business Account `2410321463128008`, test number +1 555-137-2732 (`phone_number_id` `1382503808268641`), one verified recipient. Until the GCP Secret Manager move, the system-user access token lives in AWS Secrets Manager `marginmaestro/prod` (`ap-south-1`) under key `whatsapptoken`.

**Incident (2026-09-29 to 2026-10-01).** About a minute after the first quickstart sends, Meta's automated checks raised `ACCOUNT_VIOLATION` (`violation_type: SCAM`) and disabled the business portfolio ("Permanent"). While it was disabled:
- template creation failed (`400`, subcode `3835016`);
- every send returned `200` but failed asynchronously with `131031` "Business Account locked".

A review request on 2026-09-30 restored the account by 2026-10-01. After the restore, `margin_call_notice` was created normally (`UTILITY`, id `1601248854775468`, review pending). So the template block came from the lock, **not** from a limit on test accounts, and the original decision (a pre-approved utility template) stands.

**Clarifications to the decision.**
- **A `200` from `/messages` only means "accepted".** Delivery or failure arrives on the webhook as a `statuses` event. The adapter treats the send as pending until then, and the inbound webhook (MM-G62) must also process status events, not only replies.
- **Free-form text is a secondary path.** It is allowed only inside the 24-hour customer-service window (otherwise `131047`). The adapter uses it only when `WHATSAPP_TEMPLATE_NAME` is unset; business-initiated margin calls use the template. In both cases the figures are inserted by code, never by the model (ADR-0005).
- **No silent fallback to Slack.** A failed WhatsApp delivery is a failed `DeliveryReceipt` and goes down the normal escalation path.
- **Content hygiene.** Test sends carry a clear "synthetic data" label. A message that looks like a large money demand is exactly what Meta's anti-scam checks score.
- Until MM-G62 ships, delivery errors can be read in the app dashboard under *Use cases → Connect on WhatsApp → Step 1. Try it out → Check test webhooks*.
