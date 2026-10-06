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

## Amendment (2026-10-06): per-counterparty contacts and the personalised PDF notice (G6b, MM-143, MM-144)

User decisions on 2026-10-06. They replace "every counterparty maps to the one verified test phone" and add a PDF to the notice.

**Contacts (MM-143).**
- A table `counterparty_contacts` (migration `f2a9c4e7b318`) holds one contact per (counterparty, channel): name, `phone_e164`, `active`, `updated_at`. On Postgres it has row-level security like the other counterparty-scoped tables.
- **Routing.** A notice goes to the counterparty's active contact. A counterparty without one falls back to `WHATSAPP_RECIPIENT`, so the demo keeps working for counterparties nobody has mapped. The send records which it used (`recipient_source`), the contact's id and version (its `updated_at`), and the number masked to its last four digits. The number itself is never stored outside the contacts table.
- **Acknowledge** now counts only from the number the notice was sent to: the contact's, while the contact is unchanged since the send (edited, deactivated or removed → ignored, with the reason audited), or the default for a notice sent to the default.
- **Admin CLI** `python -m persistence.contacts set --counterparty CP-1 --name "..."`, `list`, `remove`. The number is read twice from a hidden prompt (`getpass`), validated as E.164, and only its last two digits are ever printed. `remove` deletes the row.
- **Personal data.** `phone_e164` and `contact_name` are `confidential` with `llm: deny` in the data catalog: no code path sends them to a model, and a prompt containing a `+`-prefixed E.164 number is blocked. Logs, audit rows and Slack posts show masked numbers only.
- **Meta's test number** delivers only to verified recipients, at most five. A number must be added and verified in the Meta app before it is mapped here; a send to an unverified number fails asynchronously and the call escalates.

**Personalised PDF notice (MM-144), `WHATSAPP_NOTICE_PDF=on`.**
- **Template.** `margin_call_notice_v2` (id `4757283454501358`, submitted 2026-10-06, **pending** review): a DOCUMENT header plus the same four body variables and Acknowledge quick reply as v1. The PDF is uploaded first (`POST /{phone_number_id}/media`, multipart, `application/pdf`) and the media id goes in the header. Until Meta approves v2 the switch stays `off` and v1 is sent unchanged.
- **Content, all figures from code** (ADR-0005): the header (reference, counterparty, amount, deadline); "How this call was calculated" (portfolio value today and at the prior close, variation margin, initial margin with VIX, exposure, threshold after rating triggers, collateral after haircuts per type, MTA, call; the market move and its effect for an intraday call; the five largest positions); "Your CSA terms" (threshold, MTA, eligible collateral and haircuts, rating triggers, from the CSA RAG extraction already on the state, with section citations; rounding, settlement timing and dispute resolution quoted verbatim from the counterparty's CSA by one extra retrieval, no LLM). The synthetic-data label is on every page.
- **The breakdown is what the call was raised on.** The breach check stores collateral held, the effective threshold and the collateral lines on the run's state. A run checkpointed before MM-144 reads them from the database at send time.
- **One model-written paragraph.** Gemini 2.5 Flash (the cheapest model that works; about $0.0005 per notice) drafts the covering paragraph with placeholders only. Code rejects a draft with any digit or unknown placeholder (one retry), fills in the values, and the guardrail pipeline screens the prompt and the answer. The model never sees a figure, a name, a date or a phone number.
- **Failure: fail loud and escalate.** If the PDF can't be built (retrieval fails, the draft is unusable, the guardrail blocks it) or the upload fails, nothing is sent: the notice is recorded as failed, the call escalates (ServiceNow incident, Slack "NOT delivered"), and a guardrail block is audited as `guardrail_blocked`. The v1 template is **not** sent instead. That would be a silent downgrade of the notice: the approved call is meant to reach the client with its explanation, and when that is impossible a person decides what happens next, inside the SLA.
- **PDF writer.** A small dependency-free writer (`agents/pdf_writer.py`: standard Helvetica, no embedded fonts, uncompressed text). reportlab was considered: BSD-licensed, but a large new dependency for one text-only document.
- **CSA corpus.** The synthetic CSAs gained Rounding, Settlement Timing and Dispute Resolution sections. They say what the code does: no rounding, the deadline in the notice, disputes notified before the deadline and handled by a person. They reach the deployed RAG store after the documents are re-uploaded and re-ingested; until then the PDF says "Not stated in the CSA on file" for those three.
- **The webhook is unchanged for v2.** It carries the same Acknowledge button, so matching by payload or by the quoted notice works for both templates.
