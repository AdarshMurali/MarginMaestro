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
