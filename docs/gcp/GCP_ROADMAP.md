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
6. **One image, AWS stays intact until G9.** The same `adarshmurali/marginmaestro:<sha>` image runs on AWS (EC2) and GCP (Cloud Run); env flags pick the adapter (`EVENT_BUS`, `SECRETS_SOURCE`, `LLM_PROVIDER`, …). Until the G9 cut-over:
   - **Defaults stay AWS-compatible.** A GCP adapter runs only when its flag is set explicitly, so an AWS box pulling a new image behaves exactly as before.
   - **Old adapters are kept** (Kafka, OpenAI, AWS Secrets Manager, Azure SQL); removing them is G9 work, with explicit user approval.
   - **Contract tests cover both adapters** of every interface in CI, so a change that breaks the AWS path turns CI red.
   - **Database migrations must work on both** SQL Server (Azure SQL) and Postgres — every Alembic migration from G1 on is validated against both dialects.
   - **AWS runs a pinned image** (`:<sha>`, not `:latest`), bumped deliberately, so a routine `docker compose pull` can't ship untested GCP-era code to EC2.

---

> **Story keys:** `MM-G##` are roadmap placeholders. The real Jira key is written next to each one once the story is created, e.g. "MM-G05 (MM-102)". Jira (https://adarsh588.atlassian.net/browse/MM-102) is the source of truth.

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
| 20 | ~~Artifact Registry~~ | **Not used for app images** — Docker Hub stays the image registry (2026-09-29, ADR-0017): images outlive the trial and a kill-switch billing unlink, and Cloud Run pulls public Docker Hub images directly. Google-managed repos (Cloud Functions / Agent Engine builds) only | — | — | — |
| 21 | **Cloud Logging / Trace / Monitoring** | Structured JSON logs, OTel traces (one span per lifecycle step), metrics + alerts | Jaeger / Prometheus / Grafana (deployed env) | G5 | Low (free quotas) |
| 22 | **Cloud Audit Logs** | Admin + data-access logs on Cloud SQL, BigQuery, GCS, Secret Manager | — (new) | G8 | Low |
| 23 | **IAM + Workload Identity Federation** | Least-privilege service account per service; keyless GitHub Actions login (this repo, `main` only) for automated Cloud Run deploys | AWS IAM | G0, G5 | Free |
| 24 | **Cloud Billing budgets + kill-switch function** | $150 (₹12,600) cumulative trial budget (usage before credits), alerts at ≈ $25/$50/$75/$100/$125, automatic billing detach at $150 | — (new) | G0 | Free |
| — | *Non-GCP:* WhatsApp Business Cloud API | Client-facing margin-call notices + replies | Slack (client side only) | G6 | $0 (test number, ≤ 5 recipients) |
| — | *Non-GCP, unchanged:* Slack, ServiceNow PDI, GitHub Actions, SonarCloud, Terraform | Internal ops alerts, SLA escalation incidents, CI, quality, IaC | — | — | Free |

---

## Phases

### Phase G0 — GCP foundation & cost guardrails (Epic: MM-87)
ADRs: 0008, 0017

- **MM-G01** (MM-98) GCP billing budget — **$150 (₹12,600) cumulative for the trial, counting usage before credits**, alerts at ≈ $25/$50/$75/$100/$125 — and a live **billing kill-switch** at $150 (budget → Pub/Sub → function that detaches billing). Verified with a test notification in dry-run mode first.
- **MM-G02** (MM-99) Terraform `infra/gcp/`: enabled APIs, one service account per service, least-privilege IAM, a module per provider with `enable_*` toggles.
- **MM-G03** (MM-100) **Workload Identity Federation** for GitHub Actions: pool + OIDC provider trusting only this repo (numeric repo/owner IDs) on `main`; CI job `gcp-auth` proves the keyless login as `mm-ci-sa`. Images stay on **Docker Hub** (no Artifact Registry repo — ADR-0017).
- **MM-G04** (MM-101) **Secret Manager** source in `src/config/`, alongside (not replacing) the AWS source behind the same `Settings` interface; `SECRETS_SOURCE=env|aws|gcp`, unset keeps today's AWS behaviour.
- **MM-G05** (MM-102) Adapter interfaces in `src/ports/` for the dependencies that have a real second implementation: `LLMClient`, `Embedder`, `VectorStore`, `EventBus`, `Notifier`. Today's code wrapped as the first adapters in `src/adapters/` (OpenAI, Chroma, Kafka, Slack; in-memory vector store/event bus as test doubles), `adapters/factory.py` picks one per env flag (`VECTOR_STORE`, `EVENT_BUS`, `CLIENT_NOTIFIER`), contract tests in `tests/contract/`. **Dropped:** `Repository` (SQLAlchemy already is that abstraction), `Guardrail` and `Warehouse` (one implementation each — Model Armor, BigQuery — so their APIs are called directly when G3/G7 need them).

**Exit:** empty GCP project fully governed by Terraform; spend cannot exceed the threshold; all existing tests still pass through the new interfaces.

### Phase G1 — Cloud SQL Postgres, pgvector and row-level security (Epic: MM-88)
ADR: 0011

- **MM-G11** (MM-104) Local dev: `pgvector/pgvector:pg17` Postgres container **alongside** SQL Server (Chroma stays until G2); `DB_DIALECT=mssql|postgres` (default `mssql`); psycopg driver; Alembic migrations valid on both Postgres and SQL Server, proven by the CI `migrations` job (ground rule 6; Azure SQL stays live until G9).
- **MM-G12** (MM-105) LangGraph checkpoints on Postgres: our own database-neutral `SqlCheckpointSaver` (renamed from `AzureSQLSaver`) serves both SQL Server and Postgres — the official Postgres checkpointer was dropped (user decision, 2026-09-30). Its persistence test runs in CI against both databases; approval pauses survive restarts.
- **MM-G13** (MM-106) **Row-level security:** Postgres policies on every counterparty-scoped table; each transaction runs as the non-owner `mm_app` role with `FORCE ROW LEVEL SECURITY` and a `SET LOCAL app.scope` from the caller's JWT; read endpoints now require a login (frontend sends the token on reads; landing page uses public counts only). Users: margin analysts `analyst1` (CP-1…CP-4) and `analyst2` (CP-5…CP-8) see only their book; `approver`, `manager` and read-only `auditor` see everything.
- **MM-G14** (MM-107) RLS tests: a user cannot read or update another counterparty's rows, including via crafted queries and via RAG retrieval.
- **MM-G15** (MM-108) **Cloud SQL** via Terraform: `marginmaestro-pg`, Postgres 17, Enterprise `db-f1-micro`, zonal, 10 GB SSD, 7 daily backups, deletion protection, public IP with **no authorized networks** (only the Cloud SQL Auth Proxy / Connector with an IAM check gets in), IAM database users for the runtime service accounts (no passwords). Laptop access uses the **Cloud SQL Auth Proxy** (the Python Connector doesn't support our `psycopg` driver; the proxy needs no code change). Migrations + seed + `mm_app` grants run once via `scripts/cloudsql_bootstrap.ps1` as the built-in `postgres` user (password set out-of-band, never in Terraform).

**Exit:** full lifecycle runs on Postgres locally and on Cloud SQL; RLS isolation proven by tests.

> **G1 status (2026-09-30):** schema, data, checkpoints and RLS are proven on local Postgres **and Cloud SQL** (47 isolation tests + checkpoint persistence test ran against Cloud SQL). A full margin-call run (`/simulate` → approve → notify) on Postgres is verified in **G2**, when RAG moves off Chroma onto pgvector in the same database — until then that path still needs Chroma + OpenAI + Slack locally.
>
> **Closed 2026-10-01 (MM-112):** the full lifecycle ran on Postgres + pgvector + Gemini — both demo scenarios (CP-6 standard, CP-5 elite with two-person sign-off) end to end, all 8 audit steps, checkpoints persisted, 0 API errors.

### Phase G2 — Gemini on Vertex AI + RAG on pgvector (Epic: MM-89)
ADR: 0009

- **MM-G21** (MM-109) `LLM_PROVIDER=vertex`: Gemini Flash with pinned version, structured output, Pydantic validation; OpenAI/Ollama branches kept.
- **MM-G22** (MM-110) `gemini-embedding-001` (768 dims) embedder; **pgvector** `VectorStore` adapter with HNSW index + metadata filters; `retriever.py` interface unchanged.
- **MM-G23** (MM-111) RAG source documents move to **Cloud Storage**; full corpus re-ingested.
- **MM-G24** (MM-112) Golden regression set: every existing margin-call scenario gives the same orchestration decisions on Gemini as on OpenAI; retrieval precision and citation presence re-measured.

**Exit:** `make demo` passes locally on Gemini + pgvector with the same decisions as before.

### Phase G3 — AI guardrails (Epic: MM-90)
ADR: 0014

- **MM-G31** (MM-113) `Guardrail` pipeline wrapped around every LLM call (pre + post), failing closed.
- **MM-G32** (MM-114) **Model Armor** templates: prompt injection / jailbreak, malicious URLs, responsible-AI filters; attached to **Agent Gateway** (every prompt and tool response) and called directly for text outside the gateway (WhatsApp webhook).
- **MM-G37** **Semantic Governance Policies**: plain-language runtime rules (no client notification without a recorded approval; no amounts in drafts that don't match calc output). Confirm pricing first; in-code equivalents stay either way. *Moved to G5 (2026-10-01, user decision): Semantic Governance and Agent Gateway govern a deployed agent's traffic, so they land with Agent Engine (MM-G56).*
- **MM-G33** (MM-115) **Sensitive Data Protection** de-identification before LLM calls and RAG indexing; data-class filter (only allowed classes reach the model).
- **MM-G34** (MM-116) Output validation: any amount / date / counterparty in drafted text must exactly match calc output; uncited RAG claims rejected.
- **MM-G35** (MM-117) Cost / loop limits: per-run token cap, max agent steps, per-user rate limit.
- **MM-G36** (MM-117) Every verdict written to the audit trail; tests for block, mask, mismatch-reject and fail-closed paths (mocked services).

**Exit:** an injected instruction inside a CSA chunk or a client reply is blocked and audited; a draft with a wrong amount is never sent.

### Phase G4 — Pub/Sub event bus, Cloud Tasks SLA timers, Cloud Scheduler (Epic: MM-91)
ADR: 0012

- **MM-G41** (MM-119) `EventBus` Pub/Sub adapter: topics, ordering keys per counterparty, dead-letter topics; Pub/Sub emulator for local dev; Kafka adapter kept.
- **MM-G42** (MM-121) Event Agent becomes a Pub/Sub **push** endpoint on Cloud Run; idempotency re-verified under redelivery. *As built: `POST /internal/pubsub/push` (OIDC from `mm-invoker-sa`) routes prices/events to the Event Agent and `market.impact` to a new impact consumer that starts margin-call runs exactly once — the missing link between a live shock and a call. Push URLs are set in G5.*
- **MM-G43** (MM-122) **Cloud Tasks** schedules the SLA check at each call's exact deadline (replaces the re-pause polling in the SLA node). *As built: `SlaScheduler` port, `SLA_SCHEDULER=none|cloudtasks`; one named task per call (duplicates rejected by Cloud Tasks) calls `POST /internal/sla/{thread_id}/check` at the deadline, and 503 makes Cloud Tasks retry a check that fired early. Switched on in G5 with the Cloud Run URL.*
- **MM-G44** (MM-120) **Cloud Scheduler** jobs: live price refresh → `market-events`; daily BigQuery rollup trigger. *Live prices (MM-120): scheduled refresh every 5 minutes in market hours → `market.prices` → Event Agent upserts `latest_prices` and detects moves; the schedule and Cloud SQL share one on/off switch (`demo_online`).* MM-120 as built: refresh endpoint + Pub/Sub listener + subscriptions + switch; the Cloud Scheduler job itself lands in G5 with the Cloud Run URL.

**Exit:** a price shock published to Pub/Sub raises exactly one call even when the message is delivered twice; SLA breach escalates on time without polling.

### Phase G5 — Agent Platform, Cloud Run deployment, observability (Epic: MM-92)
ADRs: 0008, 0010

**G5 at a glance (order of work, 2026-10-05).** Jira key, then roadmap id:

| # | Jira | Roadmap id | Story | Status |
|---|---|---|---|---|
| 1 | MM-123 | MM-G52 | API on Cloud Run | Done |
| 2 | MM-124 | MM-G59 | Event flow switched on + live E2E | Done |
| 3 | MM-126 | MM-G57 | Automated CD to Cloud Run | Done |
| 4 | MM-127 | MM-G54 | Observability (Trace, Logging, alert) | Done |
| 5 | MM-128 | MM-G60 | Read-only MCP servers on Cloud Run | Done |
| 6 | MM-129 | MM-G51 + MM-G58 | ADK desk assistant on Agent Runtime + Sessions | Live; billing check 2026-10-06 |
| 7 | MM-130 | MM-G61 | Memory Bank | Done |
| 8 | MM-131 | MM-G56 | Agent Identity + per-tool IAM | Done (IAM per tool; Agent Identity deferred, ADR-0019) |
| 9 | MM-132 | MM-G55 | Gen AI evaluation (golden set) | Done (12/12; 0.94 / 0.90) |
| 10 | MM-125 | G5b | Margin-call policy | Done (verified live) |

- **Re-plan 2026-10-04 (user decisions).** The pricing check found Agent Runtime (formerly Agent Engine) costs $0.085/vCPU-h and $0.009/GiB-h, with 50 vCPU-h and 100 GiB-h free each month. `min_instances` defaults to 1, but 0 is allowed. The **orchestrator stays on Cloud Run**: it's a fixed pipeline with in-process tools, so moving it would be a forced fit. Agent Platform hosts the **desk assistant** (MM-G58) instead, where every feature solves a real need: Runtime + Sessions for multi-turn chat, Memory Bank for analyst/counterparty memory, Agent Identity for per-agent audit, Gen AI evaluation for checking tool choices. The assistant is built on **Google ADK** (`google-adk`; the orchestrator stays LangGraph). **Agent Gateway is rejected again:** it uses alpha APIs, needs organization-level IAM (our project has no organization) and a VPC + Cloud NAT + PSC (about $30/month). Native Cloud Run IAM, with the agent as the only invoker of each MCP service, enforces tool access instead. Stories: MM-128 … MM-132.
- **MM-G60** (MM-128) **Read-only MCP servers on Cloud Run:** `mcp-market-data`, `mcp-rag`, `mcp-margin-status` (new). One service each, so IAM grants per tool set. Private (invoker: `mm-agent-sa`, later the agent principal), streamable HTTP, scale to zero. The analyst arrives in `X-MM-User`; the role and scope are read from the database and reads run under RLS. Notifier servers are never deployed.
- **MM-G51** (MM-129) **Desk assistant on Agent Runtime + Sessions** (ADK, `min_instances=0`, 1 vCPU / 2 GiB; 24h billing check after deploy). Absorbs MM-G58's UI chat.
- **MM-G61** (MM-130) **Memory Bank:** memories per analyst and per counterparty, qualitative behaviour only (amounts always come from SQL / calc).
- **MM-G56** (MM-131) **Agent Identity** for the desk assistant (GA on Agent Runtime; project-level trust domain, no organization needed) + `roles/run.invoker` for the agent principal on each read-only MCP service. *History: Agent Gateway was dropped on 2026-10-02 because nothing called the MCP servers; on 2026-10-04 it was rejected again on cost and organization grounds (see the re-plan above).*
- **MM-G52** (MM-123) API on **Cloud Run** (min-instances 0), connected to Cloud SQL (IAM database login), Secret Manager and Pub/Sub; RAG corpus re-ingested into Cloud SQL. *MCP servers stay out of Cloud Run until MM-G58 gives them a consumer (done in MM-128).*
- ~~**MM-G53** Frontend on Cloud Run~~ — *dropped 2026-10-02: once the API has an HTTPS Cloud Run URL, the Vercel frontend works as is (free), so moving it buys nothing.*
- **MM-G54** (MM-127) OTel → **Cloud Trace**, JSON logs → **Cloud Logging**, metrics + alerts in **Cloud Monitoring** (SLA breaches, guardrail blocks, error rate). *As built: `TRACE_EXPORTER=otlp|cloudtrace|none`; one root span `margin_call_run` per orchestrator invocation; spans flushed at the end of each request; log lines carry `severity` and trace/span ids; one log-based metric + one email alert.*
- **MM-G55** (MM-132) **Gen AI evaluation** of the desk assistant (tool trajectory, grounding) on a golden question set, run from CI on demand. *As built: 12 golden cases run against the deployed agent as their users; deterministic checks (expected tool called, no tool for action requests, no out-of-scope counterparty, and every amount in an answer must match a tool result to the cent) plus Vertex AI rubrics (hallucination ≥ 0.75, final response quality ≥ 0.7). On-demand `desk-eval` workflow. The managed tool-use rubric rejected our traces, so tool choice is scored by the deterministic checks.*
- **MM-G59** (MM-124) **Switch on the event flow:** Pub/Sub push subscriptions → `/internal/pubsub/push`, Cloud Scheduler price refresh (every 5 min, market hours, paused with `demo_online`), `SLA_SCHEDULER=cloudtasks`, OIDC audience = the API URL; then the live end-to-end run on GCP.
- **MM-G57** (MM-126) **Automated CD:** `deploy-gcp` job in `ci.yml` after `build-and-push` — WIF login (MM-100), then `google-github-actions/deploy-cloudrun` with `docker.io/adarshmurali/marginmaestro:<sha>` for each Cloud Run service; `mm-ci-sa` gets `roles/run.developer` + `iam.serviceAccountUser` on the runtime accounts only. Every merge to `main` goes live with no manual step (the AWS EC2 deploy needed a manual `docker compose pull` over SSM). *As built: the roles are scoped to the one service and the one runtime account, not granted project-wide; the job smoke-tests `/health` and `/ready` and never runs two deploys at once.*

- **MM-G58** **"Ask the margin desk" analyst assistant — the MCP showcase** (user request 2026-10-02: MCP needs a real use case). A Gemini chat in the UI where the **LLM chooses tools** from our MCP servers: current/historical prices (`market_data`), CSA and policy search (`rag_retriever`), and a new read-only margin-call status tool. Tools are read-only and scoped to the user's own counterparties (row-level security); no notifier tool, so the human-approval rule holds. Guardrails screen every turn. This is where MCP earns its place: self-describing tools an LLM picks at runtime, which the fixed orchestrator pipeline never needed.

**Exit:** the full lifecycle runs end to end on GCP from the public Cloud Run URL, with one trace per run in Cloud Trace.

### Phase G5b — Margin-call policy (MM-125, under epic MM-92)
Added 2026-10-02 after the first live run on GCP. Runs after G5, before G6 (user decision).

**Why:** HPE's +7.4% move raised calls for CP-1, CP-3 and CP-7. But HPE is only 0.1–0.6% of those books, and moved their exposure by $1–4k. The calls ($250k, $162k, $3.75M) came from breaches that already existed; the HPE event only triggered a re-check of the whole portfolio. Real desks separate the two: a daily margin run catches standing exposure, and intraday calls are raised only when the event itself moves exposure materially.

- **Daily margin run:** 16:30 New York, right after the EOD price load (MM-124). Every counterparty is evaluated, and standing breaches raise calls here.
- **Intraday materiality gate:** an event raises a call only if *its own* impact on the counterparty's exposure exceeds the CSA minimum transfer amount. The call's rationale states that impact ("the HPE move increased your exposure by $X").
- **One open call per counterparty:** a new trigger while a call is open re-evaluates and updates that call instead of issuing a second one.
- **The notice quotes the enforced SLA deadline.** Today it says "next business day" while the timer is 60 minutes. G6's WhatsApp template fills the same deadline from code.
- All amounts and the materiality test stay in deterministic Python (ADR-0005), with exhaustive unit tests.

**Exit:** replaying 2026-10-02 raises no intraday HPE calls. The daily run raises the CP-1/3/7 calls once, each with its own exposure rationale. A second shock on a counterparty with an open call updates that call.

**As built (2026-10-05, ADR-0020):**
- **Daily run:** `POST /internal/margin/daily-run`, called by the Cloud Scheduler job `daily-margin-run` at 16:45 New York, Mon–Fri. That is 15 minutes after `eod-prices`, and the job is paused by `demo_online`. One impact set per day (`daily-margin-run:<date>`), so a retry is idempotent per counterparty.
- **Gate:** `calc/materiality.py` computes impact as VM change + IM change over the moved tickers, from the move carried on the event (`ImpactSet.price_moves`). Below the gate the run ends as `below_materiality`, with no call and with the impact logged and audited. `/simulate` is gated the same way.
- **One open call:** every trigger goes through `agents/margin_policy.dispatch_trigger`, under a per-counterparty lease.
  - A call still awaiting its first approval is re-evaluated in place (`reevaluate_run`); the approval gate re-arms with the new amount.
  - A call that is already signed or sent is never changed. The trigger is audited on it.
- **Notice:** quotes `{DEADLINE}` = `notification_sent_at + MARGIN_CALL_SLA_MINUTES` and the code-built `{RATIONALE}`. Both are placeholders the model never fills.

### Phase G6 — WhatsApp client notifications (Epic: MM-93)
ADR: 0016

- **MM-G61** (MM-118) ~~`whatsapp_notifier` MCP server (Cloud Run)~~ in-process WhatsApp notifier (re-planned 2026-10-05, see "As built"): approved `margin_call_notice` template, variables from calc output; `CLIENT_NOTIFIER=whatsapp|slack`.
- **MM-G62** (MM-133) Inbound webhook with `X-Hub-Signature-256` verification (handles both replies and delivery `statuses` events) → Pub/Sub → Model Armor → existing respond/dispute path.
- **MM-G63** (MM-134) Slack kept for internal approvals, escalations and SLA alerts; tests on both adapters.

**Prep done (2026-10-02):** Meta app, test number, token in Secret Manager; `margin_call_notice` template **approved**; both template and free-form sends delivered to the test phone at $0.00. See the ADR-0016 amendment.

**Exit:** an approved call reaches a verified test phone on WhatsApp; the client's reply resolves the SLA.

**As built (2026-10-05, ADR-0016 amendment), one PR for MM-118 / MM-133 / MM-134:**
- **MM-G61 re-planned (MM-118):** an **in-process `WhatsAppNotifier`** behind the `Notifier` port, not an MCP server. MCP servers are read-only (MM-128), and no LLM may reach a client-messaging tool.
  - Code formats the template's four variables (`MC-…` reference, counterparty + `(TEST)`, `USD 2,500,000.00`, the enforced deadline) and the Acknowledge payload `ack:<thread_id>`. No LLM is involved on the WhatsApp path.
  - A `200` is recorded as `accepted`. A rejected send escalates at once (ServiceNow "notice undelivered"), with no Slack fallback.
  - Settings: `CLIENT_NOTIFIER=slack|whatsapp`, `WHATSAPP_PHONE_NUMBER_ID/TEMPLATE_NAME/TEMPLATE_LANGUAGE/GRAPH_VERSION`; secrets `WHATSAPP_TOKEN/RECIPIENT`.
- **MM-G62 (MM-133):** `GET /webhooks/whatsapp` (verify-token handshake) and `POST /webhooks/whatsapp` (`X-Hub-Signature-256` with `WHATSAPP_APP_SECRET`).
  - **Inline, not Pub/Sub.** Each status and message is claimed once in `processed_events`, and an unexpected error releases the claim so Meta retries.
  - **Statuses** are audited. `failed` escalates the call.
  - **Acknowledge** = `/respond` (SLA met), only if it comes from the contact's number, for the latest notice, while the call is at the SLA step.
  - **Free text** is screened by the guardrail (fail closed), masked, audited and flagged to Slack. "Dispute" is flagged; no client-dispute path exists, so a person handles it.
- **MM-G63 (MM-134):** `INTERNAL_NOTIFIER=slack` posts once each: approval requested (+ manager second signature), client notified, client acknowledged, delivery failed, escalated (incident number), flagged replies, and the daily run summary. Defaults to `none` (AWS/local unchanged); Terraform sets `slack` on GCP.
- **Terraform:** `var.client_notifier` (default `slack`, flip to `whatsapp` after the hand-off), `var.internal_notifier` (default `slack`), and the WhatsApp non-secret settings. Output `whatsapp_webhook_url`. Secrets via `scripts/gcp_whatsapp_secrets.ps1` (merges into `marginmaestro-prod`).

**G6b as built (2026-10-06, ADR-0016 amendment), MM-143 + MM-144, one PR:**
- **MM-143, per-counterparty contacts.**
  - Table `counterparty_contacts` (migration `f2a9c4e7b318`, both dialects): one row per (counterparty, channel), with `contact_name`, `phone_e164`, `active`, `updated_at`. Row-level security on Postgres like the other counterparty-scoped tables.
  - Routing: the counterparty's active contact, else the `WHATSAPP_RECIPIENT` default (keeps the demo working for unmapped counterparties). The send records `recipient_source`, the contact's id and version, and a masked number; never the number.
  - Webhook: an Acknowledge counts only from the number the notice went to, and only while that contact is unchanged since the send (edited, deactivated or removed → ignored and audited).
  - Admin CLI `python -m persistence.contacts set|list|remove`: the number is read twice from a hidden prompt (`getpass`), validated as E.164, and shown only as its last two digits.
  - Catalog: `phone_e164` and `contact_name` are `confidential`, `llm: deny`; a `+`-prefixed E.164 number in a prompt blocks it.
- **MM-144, personalised PDF notice** (`WHATSAPP_NOTICE_PDF=off|on`, default off).
  - `agents/notice_pdf.py` builds the PDF; `agents/pdf_writer.py` is a ~200-line, dependency-free PDF writer (standard Helvetica, no embedded fonts).
  - Content: header (reference, counterparty, amount, deadline), a covering paragraph, "How this call was calculated" (MTM today/prior, VM, IM with VIX, exposure, threshold after rating triggers, collateral after haircuts per type, MTA, call; the market move and its impact for intraday calls; the five largest positions), "Your CSA terms" (threshold, MTA, eligible collateral and haircuts, rating triggers, with section citations; rounding, settlement timing and dispute resolution quoted verbatim from the CSA), and the synthetic-data label on every page.
  - The covering paragraph is the only model text: Gemini 2.5 Flash drafts with placeholders, code validates (no digits, no unknown placeholders, one retry) and fills it, and the guardrail screens it.
  - The breakdown uses figures the breach check stored on the state (`collateral_held`, `effective_threshold`, `collateral_lines`, `csa_collateral`); a run checkpointed before MM-144 reads them at send time.
  - Adapter: `POST /{phone_number_id}/media` (multipart, `application/pdf`), then template `margin_call_notice_v2` (DOCUMENT header, the same four body variables and Acknowledge button as v1). The webhook handles both templates the same way.
  - **Failure is loud:** a PDF that can't be built (retrieval, unusable draft, guardrail block) or a failed upload escalates the call. The v1 template is not sent instead.
  - The synthetic CSAs gained Rounding, Settlement Timing and Dispute Resolution sections, matching what the code does.
- **Terraform:** `var.whatsapp_notice_pdf` (default `off`) and `var.whatsapp_pdf_template_name` wired to the API's env. No new resources besides one Dataplex catalog entry generated from the catalog YAML.

### Phase G7 — BigQuery analytics & audit warehouse (Epic: MM-94)
ADR: 0013

- **MM-G71** Dataset `marginmaestro_analytics`; **Pub/Sub → BigQuery subscriptions** for events and audit (partitioned by date, clustered by counterparty).
- **MM-G72** **Threshold backtesting:** multi-year daily prices (yfinance, real) for `MARKET_UNIVERSE`; Python calc engine computes historical exposures; results analyzed in BigQuery ("which days would have triggered a call, for how much").
- **MM-G73** KPI views: SLA met/breached, time-to-approval, disputes, escalations, LLM cost and guardrail blocks.
- **MM-G74** **BigQuery ML** breach-likelihood model (advisory, shown on the dashboard only).
- **MM-G75** **Row access policies** + **policy-tag masking** matching Cloud SQL RLS; **Looker Studio** dashboard linked from the frontend.

**Exit:** an auditor can trace any call's history in BigQuery; a restricted user sees only their counterparties and masked confidential columns.

**As built (2026-10-06, PR `feature/G7-bigquery-warehouse`; Jira MM-139 / MM-140 / MM-141 / MM-142).** Scope reset by the user on 2026-10-06 (ADR-0013 amendment): a finance star schema, not an event/telemetry mirror.
- **MM-G71 → MM-139.** Dataset `marginmaestro_analytics` with 4 facts, 4 dimensions (SCD2 CSA terms) and 3 report tables, every row tagged `book` = live | historical-sim. Schemas from `src/warehouse/schemas.py` (Terraform reads the rendered JSON; tests pin it to the catalog). Policy tag `confidential` with a masking data policy on every confidential column; IAM via `warehouse_loaders` / `warehouse_readers` / `warehouse_unmasked_readers` / `warehouse_scoped_readers`. *Dropped:* Pub/Sub → BigQuery subscriptions and raw audit/LLM telemetry mirrors.
- **MM-G72 → MM-140.** The simulated historical book (1,000 synthetic counterparties, ~50k positions over the real S&P 500, 5 years of real closes, ~62M position-days), backfilled by `python -m warehouse.backfill` with the vectorized calc engine (proven equal to `calc/`), in idempotent quarter chunks.
- **MM-G73 → MM-141 / MM-142.** The live book is loaded after every daily margin run (`WAREHOUSE=bigquery`; `/internal/warehouse/daily-load` for re-runs); KPI/report tables refreshed by committed SQL. *Dropped:* LLM cost and guardrail-block KPIs (Cloud Logging covers them).
- **MM-G74 → deferred.** BigQuery ML is not built.
- **MM-G75 → MM-142.** Row access policies (scoped analysts: their live counterparties only; the simulated book is firm-wide only) and column masking. Dashboards: the in-app `/reports` page (five reports) and a Tableau Desktop guide (`docs/warehouse/tableau.md`) instead of Looker Studio.

### Phase G8 — Data governance (Epic: MM-95)
ADR: 0015

- **MM-G81** **Dataplex Universal Catalog** entries for every table and document family: owner, description, class, freshness; in-repo `docs/data_catalog.yaml` kept in sync.
- **MM-G82** Classification (`public` / `internal` / `confidential`) applied as policy tags and labels; enforced by the LLM data-class filter.
- **MM-G83** **Lineage** per margin call (price event → calc inputs → CSA chunk ids → call → approval → notification), emitted to Dataplex lineage via OpenLineage.
- **MM-G84** Data quality: fail-loud ingestion checks in code + **Dataplex data-quality scans** on BigQuery.
- **MM-G85** **Sensitive Data Protection** scans on GCS documents and BigQuery tables.
- **MM-G86** **Cloud Audit Logs** (data access) on Cloud SQL, BigQuery, GCS, Secret Manager; retention policies (GCS bucket retention, BigQuery table expiration); append-only audit enforced by DB grants.
- **MM-G88** **Security scanning in CI** (free alternatives to Black Duck / Checkmarx). Already on since 2026-09-28 via repo settings: Dependabot alerts + grouped security updates, CodeQL default setup (SAST), secret scanning + push protection. This story adds a `security` CI job: **Trivy** (container image CVEs, licence scan, Terraform misconfig), **pip-audit** (Python deps — Dependabot can't check them while `pyproject.toml` is unpinned), **gitleaks** (secrets in diffs), **Checkov** (Terraform), plus a licence allow-list that fails on GPL/AGPL. Findings uploaded as SARIF to the Security tab. See ADR-0018.
- **MM-G87** Governance docs: section in `docs/ARCHITECTURE.md` and `docs/DATA_SOURCES.md`; tests for each quality, masking and classification rule.

**Exit:** every dataset has an owner and class; any call is traceable to its source data and cited documents; bad data is rejected loudly; confidential fields never reach the LLM unmasked.

**As built (2026-10-05, PR `feature/G8-governance`; Jira MM-135 / MM-136 / MM-137).** BigQuery is parked with G7 (user decision 2026-10-05), so every BigQuery item below is **deferred with G7**. See the ADR-0015 amendment.
- **MM-G81 → MM-135.** `docs/data_catalog.yaml` covers all 16 Cloud SQL tables (every column classified) and all 5 GCS document families; a sync test guards it. Dataplex entries are generated from the YAML (`infra/gcp/dataplex.tf`). *Deferred:* BigQuery tables.
- **MM-G82 → MM-135.** Per-column classes, enforced by the LLM data-class filter (`governance/classification.py`: pseudonymize names, mask sizes and values, deny secrets) in `GuardedLLM` and the MCP RAG tool. Labels go on the Dataplex entries. *Deferred:* BigQuery policy tags.
- **MM-G83 → MM-136.** OpenLineage per margin call to the Data Lineage API (`LINEAGE_EXPORTER=datalineage`), best effort.
- **MM-G84.** Fail-loud ingestion checks in code are unchanged. *Deferred:* Dataplex data-quality scans (BigQuery).
- **MM-G85 → MM-137.** Scheduled SDP inspection of the documents bucket, with `python -m governance.sdp_scan` for the summary. *Deferred:* BigQuery scans.
- **MM-G86 → MM-137.**
  - Cloud Audit Logs data access on Cloud SQL, GCS and Secret Manager.
  - GCS retention policy of 30 days, unlocked.
  - `audit_log` append-only by grant (migration `e3f8a1c5d927`, Postgres CI test).
  - *Deferred:* BigQuery audit logs and table expiration.
- **MM-G88 → MM-137.** The CI `security` job: pip-audit, licence allow-list, gitleaks, Trivy (image, config) and Checkov, with SARIF uploaded to the Security tab. The Dockerfile now takes Debian security updates and current pip/setuptools.
- **MM-G87 → MM-137.** Governance sections in `docs/ARCHITECTURE.md` (§10) and `docs/DATA_SOURCES.md` (§6a), with tests for each catalog, classification, masking and lineage rule.

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
