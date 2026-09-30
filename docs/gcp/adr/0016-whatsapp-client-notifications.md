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

## Amendment (2026-09-30): free-form messages on the test account

**Finding.** Meta's free *Test WhatsApp Business Account* cannot create templates. The WhatsApp Manager "Create template" button is disabled, and `POST /{waba_id}/message_templates` returns `400`, subcode `3835016` ("WhatsApp Business account restricted from creating a new template"). The account only holds Meta's pre-seeded samples (`hello_world`, `jaspers_market_*`). So the `margin_call_notice` template above cannot exist at $0.

**Amended decision.**
- While on the test account, the WhatsApp adapter sends the margin-call notice as a **free-form text message** (`type: text`). This is allowed for 24 hours after the recipient last messaged the business number (the customer-service window). The body is still rendered by code from calc output, so the amounts are never written by the model (ADR-0005).
- The adapter uses the template when `WHATSAPP_TEMPLATE_NAME` is set, and free-form text otherwise. Moving to a real, verified number with an approved `margin_call_notice` template becomes a config change, not a code change.
- If Meta rejects a send because the 24-hour window is closed (error `131047`), the adapter fails loudly. The notifier returns a failed `DeliveryReceipt`, and the escalation path treats it like any other delivery failure. The adapter never silently falls back to Slack.

**Consequences.**
- For the demo, each verified recipient has to message the test number (e.g. "hi") within 24 hours before a call is raised. This is a documented demo setup step.
- The pure business-initiated path (a first message to a client, outside the window) is not available until a real number and an approved template exist. Accepted for the POC.
- Secrets: the access token lives in `marginmaestro/prod` (AWS Secrets Manager, `ap-south-1`) under key `whatsapptoken` until the GCP Secret Manager move.
