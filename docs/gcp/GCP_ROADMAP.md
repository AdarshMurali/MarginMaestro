# MarginMaestro — GCP Roadmap

> **Status:** Approved plan, not started (2026-09-28). This replaces the old `docs/ROADMAP.md` Phases 14 (GCP portability), 15 (data governance) and 16 (Gemini Live voice). Everything below is **mandatory**, not optional — except Gemini Live, which is dropped (ADR-0009).
>
> **This folder (`docs/gcp/`):** `GCP_ROADMAP.md` (this plan), `GCP_PROGRESS.md` (progress log for this track), `GCP_ARCHITECT_QUESTIONS.md` (architect-session prep), `adr/` (ADR-0008 … ADR-0017). Numbering continues from the project-wide ADRs in `docs/adr/`.
> **Earlier drafts** (`GCP_MIGRATION.md`, `GCP_DEPLOYMENT_PLAN.md`) were merged into this file and removed; their still-relevant points are in *Background notes* at the end.

## Ground rules for this track

1. **GCP-native services only** while the $300 / 90-day trial credits last.
2. **Month-2 cost review (~2026-11-28):** swap any piece that would bill after the trial to its free fallback (ADR-0017). The app is a demo and is stopped rather than paid for.
3. **Every external dependency sits behind an interface + env flag**, so a single piece can be swapped without touching the rest (ADR-0017).
4. **Golden rules are unchanged:** LLM never does math (ADR-0005), human approval before any client-facing message, idempotent event processing, tests + ≥ 80% coverage per story.
5. Same working loop as `docs/ROADMAP.md`: one story at a time, Jira ticket per story, handoff entry in **`docs/gcp/GCP_PROGRESS.md`** (not the main `docs/PROGRESS.md`). Epic keys are real Jira keys (MM-87 … MM-97); story keys below are placeholders (`MM-G#`) until each phase's stories are created in Jira when the phase starts.

---

## GCP services and what each is used for

| # | Service | What we use it for | Replaces | Phase | Post-trial cost risk → fallback |
|---|---|---|---|---|---|
| 1 | **Cloud Run** | API, MCP servers (market data, RAG, Slack, WhatsApp, ServiceNow), Pub/Sub push consumers, WhatsApp webhook, frontend | EC2 + EIP, Vercel | G0, G5 | Low (free tier, min-instances 0) |
| 2 | **Vertex AI – Gemini (Flash)** | Reasoning: CSA interpretation, dispute rationale, impact judgment, drafting notice text | OpenAI `gpt-4o-mini` | G2 | Medium → AI Studio free tier / OpenAI |
| 3 | **Vertex AI – `gemini-embedding-001`** | Embeddings for the RAG corpus and queries (768 dims) | `text-embedding-3-small` | G2 | Medium → same as above |
| 4 | **Vertex AI Agent Engine** (Agent Platform) | Managed runtime for the LangGraph orchestrator; sessions, tracing | in-process graph in the API | G5 | High → in-process on Cloud Run |
| 4a | **Agent Identity** (Agent Platform) | Per-agent identity instead of a shared service account; every tool call audited to the agent | shared service account | G5 | Low |
| 4b | **Agent Gateway** (Agent Platform) | Single control point for agent → MCP tool / Gemini traffic; deny-by-default IAM tool policies; Model Armor attached | direct tool calls | G3, G5 | Unknown (pricing not published) → in-code tool allow-list |
| 4c | **Semantic Governance Policies** (Agent Platform) | Plain-language runtime rules, e.g. no client notification without a recorded approval | — (new) | G3 | Unknown (billing starts later in 2026) → in-code approval check |
| 5 | **Vertex AI Gen AI evaluation** | Golden-scenario evaluation: tool trajectory, grounding, citation coverage | — (new) | G5 | Low (on-demand only) |
| 6 | **Cloud SQL for PostgreSQL** | Transactional store: counterparties, trades, exposures, calls, approvals, audit, LangGraph checkpoints; **row-level security** | Azure SQL | G1 | **High** → Neon / Supabase free Postgres |
| 7 | **pgvector** (in Cloud SQL) | RAG vector store with metadata filters; RLS applies to retrieval | ChromaDB | G1, G2 | same as Cloud SQL |
| 8 | **Pub/Sub** | Event bus: market events, margin-call events, notifications, audit; ordering keys per counterparty; dead-letter topics; BigQuery subscriptions | Kafka / Redpanda | G4 | Low (10 GB/mo free) |
| 9 | **Cloud Tasks** | Fires the SLA-deadline check at the exact deadline for each notified call | re-pause polling in the SLA node | G4 | Low (free tier) |
| 10 | **Cloud Scheduler** | Periodic jobs: live price refresh → Pub/Sub, daily BigQuery rollups, backtest refresh | always-on poller / EventBridge | G4 | Low (3 jobs free) |
| 11 | **BigQuery** | Analytics + audit warehouse: event history, threshold backtesting, SLA/approval KPIs, LLM + guardrail telemetry, row access policies, masked columns | — (new) | G7 | Low (free tier) |
| 12 | **BigQuery ML** | Advisory breach-likelihood model (never raises or sizes a call) | — (new) | G7 | Low (free tier) |
| 13 | **Looker Studio** | Dashboards on BigQuery views, linked from the frontend | Grafana (deployed env) | G7 | Free |
| 14 | **Model Armor** | Prompt-injection / jailbreak / malicious-URL screening on inputs (client replies, retrieved chunks) and outputs | — (new) | G3 | Low–Med → in-code checks |
| 15 | **Sensitive Data Protection** | PII / account-number detection and masking before LLM calls and RAG indexing; scans of GCS and BigQuery | — (new) | G3, G8 | Low–Med → Presidio |
| 16 | **Dataplex Universal Catalog** | Data catalog, classification, lineage (OpenLineage), data-quality scans | — (new) | G8 | Medium → governance-as-code |
| 17 | **BigQuery policy tags** | Column-level classification + dynamic masking of confidential fields | — (new) | G7, G8 | Free |
| 18 | **Cloud Storage** | RAG source documents (CSA, policy, escalation), with a retention policy | S3 bucket | G2 | Low (5 GB free) |
| 19 | **Secret Manager** | All secrets as one JSON secret per env (`marginmaestro-<app_env>`) | AWS Secrets Manager | G0 | Low |
| 20 | **Artifact Registry** | Container images | Docker Hub (kept as mirror) | G0 | Low (0.5 GB free) |
| 21 | **Cloud Logging / Trace / Monitoring** | Structured JSON logs, OTel traces (one span per lifecycle step), metrics + alerts | Jaeger / Prometheus / Grafana (deployed env) | G5 | Low (free quotas) |
| 22 | **Cloud Audit Logs** | Admin + data-access logs on Cloud SQL, BigQuery, GCS, Secret Manager | — (new) | G8 | Low |
| 23 | **IAM + Workload Identity Federation** | Least-privilege service account per service; keyless GitHub Actions deploys | AWS IAM | G0 | Free |
| 24 | **Cloud Billing budgets + kill-switch function** | $150 (₹12,600) cumulative trial budget (usage before credits), alerts at ≈ $25/$50/$75/$100/$125, automatic billing detach at $150 | — (new) | G0 | Free |
| — | *Non-GCP:* WhatsApp Business Cloud API | Client-facing margin-call notices + replies | Slack (client side only) | G6 | $0 (test number, ≤ 5 recipients) |
| — | *Non-GCP, unchanged:* Slack, ServiceNow PDI, GitHub Actions, SonarCloud, Terraform | Internal ops alerts, SLA escalation incidents, CI, quality, IaC | — | — | Free |

---

## Phases

### Phase G0 — GCP foundation & cost guardrails (Epic: MM-87)
ADRs: 0008, 0017

- **MM-G01** (MM-98) GCP billing budget — **$150 (₹12,600) cumulative for the trial, counting usage before credits**, alerts at ≈ $25/$50/$75/$100/$125 — and a live **billing kill-switch** at $150 (budget → Pub/Sub → function that detaches billing). Verified with a test notification in dry-run mode first.
- **MM-G02** Terraform `infra/gcp/`: enabled APIs, one service account per service, least-privilege IAM, a module per provider with `enable_*` toggles.
- **MM-G03** Workload Identity Federation for GitHub Actions; CI pushes images to **Artifact Registry**.
- **MM-G04** **Secret Manager** source in `src/config/` (replaces `secrets_manager.py`'s AWS source behind the same `Settings` interface; `SECRETS_SOURCE=gcp|aws|env`).
- **MM-G05** Adapter interfaces scaffolded: `LLMClient`, `Embedder`, `VectorStore`, `Repository`, `EventBus`, `Notifier`, `Guardrail`, `Warehouse`, plus a shared contract-test harness. The existing implementations become the first adapters (no behavior change).

**Exit:** empty GCP project fully governed by Terraform; spend cannot exceed the threshold; all existing tests still pass through the new interfaces.

### Phase G1 — Cloud SQL Postgres, pgvector and row-level security (Epic: MM-88)
ADR: 0011

- **MM-G11** Local dev: `pgvector/pgvector` Postgres container replaces SQL Server + Chroma in Docker Compose; `psycopg` driver; Alembic migrations ported and re-validated.
- **MM-G12** LangGraph checkpointing moves to the official Postgres checkpointer (replaces `persistence/db/checkpoint_saver.py`); approval pauses survive restarts.
- **MM-G13** **Row-level security:** policies on all counterparty-scoped tables; app connects as a non-owner role with `FORCE ROW LEVEL SECURITY`; request-scoped `SET LOCAL app.user_role / app.counterparty_scope` from the JWT; `auditor` read-only role.
- **MM-G14** RLS tests: a user cannot read or update another counterparty's rows, including via crafted queries and via RAG retrieval.
- **MM-G15** Provision **Cloud SQL** (smallest shared-core, no HA) via Terraform; IAM DB auth via the Cloud SQL Python Connector; seed via `batch_loader` / `seed_users`.

**Exit:** full lifecycle runs on Postgres locally and on Cloud SQL; RLS isolation proven by tests.

### Phase G2 — Gemini on Vertex AI + RAG on pgvector (Epic: MM-89)
ADR: 0009

- **MM-G21** `LLM_PROVIDER=vertex`: Gemini Flash with pinned version, structured output, Pydantic validation; OpenAI/Ollama branches kept.
- **MM-G22** `gemini-embedding-001` (768 dims) embedder; **pgvector** `VectorStore` adapter with HNSW index + metadata filters; `retriever.py` interface unchanged.
- **MM-G23** RAG source documents move to **Cloud Storage**; full corpus re-ingested.
- **MM-G24** Golden regression set: every existing margin-call scenario gives the same orchestration decisions on Gemini as on OpenAI; retrieval precision and citation presence re-measured.

**Exit:** `make demo` passes locally on Gemini + pgvector with the same decisions as before.

### Phase G3 — AI guardrails (Epic: MM-90)
ADR: 0014

- **MM-G31** `Guardrail` pipeline wrapped around every LLM call (pre + post), failing closed.
- **MM-G32** **Model Armor** templates: prompt injection / jailbreak, malicious URLs, responsible-AI filters; attached to **Agent Gateway** (every prompt and tool response) and called directly for text outside the gateway (WhatsApp webhook).
- **MM-G37** **Semantic Governance Policies**: plain-language runtime rules (no client notification without a recorded approval; no amounts in drafts that don't match calc output). Confirm pricing first; in-code equivalents stay either way.
- **MM-G33** **Sensitive Data Protection** de-identification before LLM calls and RAG indexing; data-class filter (only allowed classes reach the model).
- **MM-G34** Output validation: any amount / date / counterparty in drafted text must exactly match calc output; uncited RAG claims rejected.
- **MM-G35** Cost / loop limits: per-run token cap, max agent steps, per-user rate limit.
- **MM-G36** Every verdict written to the audit trail; tests for block, mask, mismatch-reject and fail-closed paths (mocked services).

**Exit:** an injected instruction inside a CSA chunk or a client reply is blocked and audited; a draft with a wrong amount is never sent.

### Phase G4 — Pub/Sub event bus, Cloud Tasks SLA timers, Cloud Scheduler (Epic: MM-91)
ADR: 0012

- **MM-G41** `EventBus` Pub/Sub adapter: topics, ordering keys per counterparty, dead-letter topics; Pub/Sub emulator for local dev; Kafka adapter kept.
- **MM-G42** Event Agent becomes a Pub/Sub **push** endpoint on Cloud Run; idempotency re-verified under redelivery.
- **MM-G43** **Cloud Tasks** schedules the SLA check at each call's exact deadline (replaces the re-pause polling in the SLA node).
- **MM-G44** **Cloud Scheduler** jobs: live price refresh → `market-events`; daily BigQuery rollup trigger.

**Exit:** a price shock published to Pub/Sub raises exactly one call even when the message is delivered twice; SLA breach escalates on time without polling.

### Phase G5 — Agent Platform, Cloud Run deployment, observability (Epic: MM-92)
ADRs: 0008, 0010

- **MM-G51** Deploy the LangGraph orchestrator to **Vertex AI Agent Engine**; API calls it for simulate / approve / resume (`AGENT_RUNTIME=agent_engine|cloudrun`). Check idle pricing first (does it keep an instance warm?).
- **MM-G56** **Agent Identity** for the orchestrator + **Agent Gateway** in front of all MCP servers and Gemini, with deny-by-default IAM tool policies per agent; MCP servers registered behind the gateway.
- **MM-G52** API + MCP servers on **Cloud Run** (min-instances 0), connected to Cloud SQL, Secret Manager and Pub/Sub.
- **MM-G53** Frontend on **Cloud Run** (HTTPS by default, which removes the mixed-content rewrite workaround); Vercel kept as fallback.
- **MM-G54** OTel → **Cloud Trace**, JSON logs → **Cloud Logging**, metrics + alerts in **Cloud Monitoring** (SLA breaches, guardrail blocks, error rate).
- **MM-G55** **Gen AI evaluation** run on the golden scenario set from CI (on demand).

**Exit:** the full lifecycle runs end to end on GCP from the public Cloud Run URL, with one trace per run in Cloud Trace.

### Phase G6 — WhatsApp client notifications (Epic: MM-93)
ADR: 0016

- **MM-G61** `whatsapp_notifier` MCP server (Cloud Run): approved `margin_call_notice` template, variables from calc output; `CLIENT_NOTIFIER=whatsapp|slack`.
- **MM-G62** Inbound webhook with `X-Hub-Signature-256` verification → Pub/Sub → Model Armor → existing respond/dispute path.
- **MM-G63** Slack kept for internal approvals, escalations and SLA alerts; tests on both adapters.

**Exit:** an approved call reaches a verified test phone on WhatsApp; the client's reply resolves the SLA.

### Phase G7 — BigQuery analytics & audit warehouse (Epic: MM-94)
ADR: 0013

- **MM-G71** Dataset `marginmaestro_analytics`; **Pub/Sub → BigQuery subscriptions** for events and audit (partitioned by date, clustered by counterparty).
- **MM-G72** **Threshold backtesting:** multi-year daily prices (yfinance, real) for `MARKET_UNIVERSE`; Python calc engine computes historical exposures; results analyzed in BigQuery ("which days would have triggered a call, for how much").
- **MM-G73** KPI views: SLA met/breached, time-to-approval, disputes, escalations, LLM cost and guardrail blocks.
- **MM-G74** **BigQuery ML** breach-likelihood model (advisory, shown on the dashboard only).
- **MM-G75** **Row access policies** + **policy-tag masking** matching Cloud SQL RLS; **Looker Studio** dashboard linked from the frontend.

**Exit:** an auditor can trace any call's history in BigQuery; a restricted user sees only their counterparties and masked confidential columns.

### Phase G8 — Data governance (Epic: MM-95)
ADR: 0015

- **MM-G81** **Dataplex Universal Catalog** entries for every table and document family: owner, description, class, freshness; in-repo `docs/data_catalog.yaml` kept in sync.
- **MM-G82** Classification (`public` / `internal` / `confidential`) applied as policy tags and labels; enforced by the LLM data-class filter.
- **MM-G83** **Lineage** per margin call (price event → calc inputs → CSA chunk ids → call → approval → notification), emitted to Dataplex lineage via OpenLineage.
- **MM-G84** Data quality: fail-loud ingestion checks in code + **Dataplex data-quality scans** on BigQuery.
- **MM-G85** **Sensitive Data Protection** scans on GCS documents and BigQuery tables.
- **MM-G86** **Cloud Audit Logs** (data access) on Cloud SQL, BigQuery, GCS, Secret Manager; retention policies (GCS bucket retention, BigQuery table expiration); append-only audit enforced by DB grants.
- **MM-G87** Governance docs: section in `docs/ARCHITECTURE.md` and `docs/DATA_SOURCES.md`; tests for each quality, masking and classification rule.

**Exit:** every dataset has an owner and class; any call is traceable to its source data and cited documents; bad data is rejected loudly; confidential fields never reach the LLM unmasked.

### Phase G9 — Cut-over & decommission (Epic: MM-96)

- **MM-G91** `make demo` passes against the GCP deployment; README / architecture diagrams updated for GCP; `CLAUDE.md` tech stack updated.
- **MM-G92** Decommission AWS (EC2, EIP, EventBridge schedule, S3, Secrets Manager) and remove MarginMaestro's schema from Azure SQL — each only with explicit user approval.

**Exit:** GCP is the only runtime; AWS/Azure costs for MarginMaestro are $0.

### Phase G10 — Month-2 cost review (~2026-11-28) (Epic: MM-97)
ADR: 0017

- **MM-G101** Review actual billing per service against the credits burned.
- **MM-G102** Swap post-trial cost items to their fallbacks via env flags + Terraform toggles: Cloud SQL → Neon/Supabase, Agent Engine → Cloud Run in-process, Vertex AI → AI Studio free tier / OpenAI, Dataplex scans → governance-as-code, Model Armor/SDP → in-code + Presidio (only if over quota).
- **MM-G103** Re-run the full contract-test suite and `make demo` on the post-trial configuration.

**Exit:** projected post-trial monthly cost is $0 (always-free quotas only), with the kill-switch still armed.

---

## Open items — revisit at the end of the track

Raised by the user 2026-09-28. Not scheduled into a phase yet; pick up after G8, before G9 cut-over.

1. **ISDA Master Agreement documents must be *necessary*, not nice-to-have.** Old ROADMAP Phase 13 (MM-130..133) only adds ISDA as extra RAG context. Before building it, find a use case where the lifecycle genuinely can't be right without it. Candidates to evaluate:
   - **Event of Default / Termination Event gating:** if a counterparty has an ISDA Event of Default (e.g. failure to pay a prior margin call past the grace period), the next step is close-out netting, not another margin call — the orchestrator must branch on ISDA terms.
   - **Close-out netting amount:** on default, exposure is netted across *all* trades under the ISDA Master, not per CSA — the netting set definition lives in the ISDA, so the calc input depends on it (calc stays deterministic, ADR-0005).
   - **Cross-default / Additional Termination Events** (e.g. rating downgrade below a threshold) that change collateral obligations or trigger termination.
   - **Governing law / dispute resolution** clause deciding which dispute path and deadlines apply.
   Pick the one(s) that change an orchestration decision or a calc input; that is what makes ISDA necessary.
2. **BigQuery needs a firm reporting requirement, not just analytics.** G7 lists the use cases; before building it, pin down the concrete report(s) that would force a warehouse. Candidates:
   - **Regulatory margin reporting** (e.g. UMR / EMIR-style daily collateral and margin-call reports per counterparty, with a history that can't live on the OLTP DB).
   - **Audit / model-risk evidence pack** (SR 11-7 style): every call's inputs, LLM version, guardrail verdicts and approvals over a period, queryable by an auditor.
   - **Management reporting:** daily exposure/collateral dashboard, SLA breach trends, dispute rates by counterparty tier.
   Decide which report is the primary requirement and design G7's tables around it.

## Out of scope

- **Gemini Live API** voice notifications — rejected (ADR-0009).
- **Vertex AI Vector Search, Vertex AI RAG Engine, AlloyDB** — rejected on cost (ADR-0011).
- **Rewriting agents in ADK** — rejected; LangGraph stays (ADR-0010).
- **Agent Platform's RAG Engine and Vector Search** — rejected: paid/always-on and can't apply our row-level security; pgvector instead (ADR-0010, ADR-0011).
- **Flink** — still deferred (ADR-0003).

---

## Background notes (merged from the earlier drafts)

- **Hackathon context:** hack2skill's AI Builder Cup 2026 (GCP-themed), **BFSI track**. Team name: MarginMaestro. Description (240 chars): "MarginMaestro automates the margin-call lifecycle end-to-end: detects exposure breaches, drafts approval-gated client notices, tracks SLA timers, and escalates breaches. Powered by Gemini agent orchestration and RAG over policy docs on GCP."
- **Document AI — rejected:** source CSA/ISDA PDFs are born-digital, so plain text extraction already covers them; Document AI's OCR adds nothing here.
- **BigQuery public datasets:** for G7, consider joining against a free `bigquery-public-data` dataset (SEC financials or a macro/market set) for extra analytical depth; only bytes scanned count against the free 1 TB. Pick the dataset when G7 starts.
- **Regulatory framing worth naming in the pitch:** SR 11-7-style model risk management (model version pinning + golden regression set), EU AI Act "high-risk" framing for financial-decision systems, SOC 2-style access control.
- **Production-grade controls documented but not enabled (cost):** VPC Service Controls around Vertex AI / Cloud SQL / GCS, CMEK via Cloud KMS, Access Transparency.
- **Unity Catalog comparison:** GCP splits it across Dataplex (data catalog, lineage, quality, access) and Vertex AI Model Registry + Model Monitoring (AI assets). See `GCP_ARCHITECT_QUESTIONS.md`.
