# ADR-0016: WhatsApp for client notifications, Slack kept for internal ops

- **Status:** Accepted
- **Date:** 2026-09-28

## Context

Approved margin calls are currently posted to Slack. A real counterparty is far more likely to be reached on WhatsApp than in our Slack workspace. GCP has no first-party WhatsApp service, so this is the one non-GCP integration in the plan.

## Decision

- **Client-facing margin-call notices** go out over the **WhatsApp Business Cloud API** (Meta, direct) via a new `whatsapp_notifier` MCP server on Cloud Run. *(Superseded 2026-10-05: an in-process adapter, see the last amendment.)*
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

## Amendment (2026-10-05): as built in G6 (MM-118, MM-133, MM-134)

User decisions on 2026-10-05, and what they changed in the design above.

**In-process notifier, not an MCP server.** The decision said the notices go "via a new `whatsapp_notifier` MCP server on Cloud Run". That is dropped. MM-128 exposes only read-only MCP servers, and a tool that messages clients must never be reachable by an LLM. `adapters/whatsapp_adapter.py` (`WhatsAppNotifier`) is an in-process adapter behind the `Notifier` port. It is called only by the orchestrator's `send_notification` node, which runs only after the approval gate. No MCP tool, agent or endpoint can send a client message.

**Channel split.** Both channels stay:
- **WhatsApp** carries counterparty notices and client replies (`CLIENT_NOTIFIER=whatsapp`).
- **Slack** carries internal firm traffic (`INTERNAL_NOTIFIER=slack`, `agents/internal_notifications.py`): approval requested (and the manager's second signature for the elite tier), client notified, client acknowledged, delivery failed, escalated (with the ServiceNow incident number), flagged client replies, and the daily margin run summary.
- Each internal post is sent once: its key is claimed in `processed_events`. A replayed graph node or a redelivered webhook never posts twice. A failed internal post is logged at error level and never fails the margin call.
- `CLIENT_NOTIFIER=slack` keeps the pre-G6 behaviour (the LLM-drafted notice posted to Slack). AWS and local are unchanged; `INTERNAL_NOTIFIER` defaults to `none`.

**The notice.** No LLM is involved on the WhatsApp path. Code builds `ClientNotice` (`agents/client_notice.py`):
- Reference `MC-` + 8 hex characters of the thread id's SHA-256.
- Counterparty display name plus `CLIENT_NOTICE_LABEL` (default `(TEST)`).
- Amount as `USD 2,500,000.00`.
- Deadline from `format_deadline`, the same instant the SLA timer enforces.

The adapter sends `margin_call_notice` with those four body variables in that order. The quick-reply button payload is `ack:<thread_id>`, and `biz_opaque_callback_data` is the thread id, so each status event maps to its call without a lookup. Template name, language and Graph version are settings. A `200` gives a receipt with status `accepted`, not delivered.

**Recipients.** For the demo, every counterparty maps to the one verified test phone (`WHATSAPP_RECIPIENT`). Production would read a per-counterparty contact table with consent records.

**Failure → escalation.** A send that raises (`ClientDeliveryError`: not configured, rejected, network) is recorded as a failed `NotificationResult`. The run sets `delivery_failure` and `sla_outcome="breached"` (the client can't meet a call it never received) and goes straight to `escalate`. A later `failed` status from the webhook does the same through the SLA step. The ServiceNow incident says "notice undelivered" with Meta's error. No other channel is tried.

**Webhook** (`api/whatsapp_webhook.py`):
- `GET /webhooks/whatsapp` is Meta's verification handshake. It echoes `hub.challenge` only when `hub.verify_token` matches `WHATSAPP_VERIFY_TOKEN` (constant-time compare). It is the one deliberately public GET added to the MM-106 allow-list.
- `POST /webhooks/whatsapp` checks `X-Hub-Signature-256` (HMAC-SHA256 of the raw body with `WHATSAPP_APP_SECRET`, constant time) before parsing anything: 401 if it fails, 503 if unconfigured.
- **Processed inline, not via Pub/Sub.** Each status (`wa-status:<id>:<status>`) and message (`wa-msg:<id>`) is claimed in `processed_events` first, so Meta's redeliveries are skipped. An unexpected error releases the claim and returns 500, and Meta retries. A Pub/Sub hop would add a topic, a subscription and a second claim for work that is one audit row and at most one graph resume.
- **Statuses** go on the call's audit trail. `failed` for the call's current notice, while it waits for the client, escalates.
- **Acknowledge** resolves the SLA, the same as `POST /margin-calls/{id}/respond`, but only if three things hold: the sender is the counterparty's contact, the button belongs to the call's latest notice, and the call is at the SLA step.
- **Free text** is screened by the guardrail pipeline (fail closed: unscreenable text counts as blocked), masked by the redactor, audited, and flagged to Slack for a person. Blocked text is withheld. A reply containing "dispute" is flagged as a possible dispute; no automatic dispute path exists, so a person handles it. No LLM acts on client messages.
