# CLAUDE.md — Agent Operating Guide

> **Read this first, every session.** This is the operating contract for anyone (human or Claude agent) working on MarginMaestro. Keep it lean and high-signal. When a convention solidifies or a recurring mistake appears, add a one-line rule here rather than re-explaining each session.

## What this project is

**MarginMaestro** automates the end-to-end **margin call lifecycle** using **LLM agent orchestration**, a **RAG pipeline** over legal/policy documents, and a **real-time streaming** backbone. A market event moves prices → exposure is recomputed → if a threshold breaks, a margin call is raised, a human approves it, the client is notified via Slack, an SLA timer runs, and non-response escalates to ServiceNow — with a full audit trail throughout.

It is a **portfolio / proof-of-concept** built to production-engineering standards. Data is **free + synthetic**. Margin math is **directionally correct**, not a certified risk model.

## Golden rules (do not violate)

1. **LLM for reasoning, code for math.** NEVER compute MTM, VM, IM, thresholds, or any number with the LLM. Financial calculations are deterministic Python with exhaustive unit tests. The LLM is only for: RAG over documents, dispute rationale, entity/impact judgment, and drafting notification text. (See `docs/adr/0005`.)
2. **No secrets in code.** All config/secrets via env vars locally and **AWS Secrets Manager** (a single JSON secret, `marginmaestro/<app_env>`) in deployed envs; AWS Parameter Store remains available for non-secret config. Never hardcode keys, tokens, or connection strings. `.env` is git-ignored; only `.env.example` is committed.
3. **One story at a time, fully finished.** Follow the loop in `CONTRIBUTING.md`. Do not start the next story until the current one meets the Definition of Done and `docs/PROGRESS.md` is updated.
4. **Tests are mandatory.** Every story ships with tests. Coverage must stay ≥ 80%. Mock the LLM in tests; assert on orchestration decisions, not model prose.
5. **Human-in-the-loop is a feature.** A margin call is never fired fully autonomously — there is always an approval gate before a client-facing call goes out.
6. **Keep the frontend thin.** It visualizes state; it holds no business logic.
7. **Curated demo universe.** Entity/impact mapping runs over a small fixed set of tickers/counterparties (see `MARKET_UNIVERSE`), not open-world news. Do not over-promise general entity resolution.

## Tech stack (don't swap without an ADR)

> **Live runtime: Google Cloud** (GCP track, `docs/gcp/`). The original AWS EC2 + Azure SQL deployment is paused pending decommission (MM-G92). Adapters keep the pre-GCP stack runnable locally by env flag (ADR-0017).

- **Orchestration:** LangGraph for the margin-call workflow (explicit state-graph, on Cloud Run); **Google ADK** for the conversational desk assistant on **Vertex AI Agent Runtime** (Sessions + Memory Bank; ADR-0019).
- **LLM:** **Gemini on Vertex AI** (`LLM_PROVIDER=vertex`) on GCP, every call through the guardrail pipeline (Model Armor + in-code, SDP masking, the catalog-driven data-class filter). OpenAI `gpt-4o-mini` remains the local/fallback provider (ADR-0006).
- **Embeddings:** Vertex AI text embeddings on GCP; OpenAI `text-embedding-3-small` locally. Query and document embeddings must share one model (ADR-0006).
- **Relational + RAG store:** **Cloud SQL Postgres + pgvector** with row-level security (ADR-0011); ChromaDB / SQL Server remain for local dev. **Documents:** Cloud Storage.
- **Eventing:** **Pub/Sub** push, **Cloud Tasks** (one SLA timer per call), **Cloud Scheduler** (price refresh, EOD closes, daily margin run) on GCP; Kafka (Redpanda) locally. Flink is **deferred** (`docs/adr/0003`).
- **Observability:** OpenTelemetry traces (one root span per margin-call run) to **Cloud Trace** on GCP, Jaeger locally; structured logs to **Cloud Logging**; incident alert in **Cloud Monitoring**. Locally, **Prometheus** scrapes `GET /metrics` and **Grafana** (host port `3001`) auto-provisions from `infra/grafana/`.
- **API:** FastAPI on **Cloud Run** (scale to zero). **Frontend:** Next.js on Vercel.
- **Governance (G8):** Dataplex catalog generated from `docs/data_catalog.yaml`, Data Lineage per margin call, data-access audit logs, append-only audit trail.
- **Warehouse (G7):** **BigQuery** `marginmaestro_analytics` — finance star schema for the live book (loaded after each daily margin run, `WAREHOUSE=bigquery`) and a warehouse-only simulated book (1,000 synthetic counterparties, 5 years of real closes). Every query sets `maximum_bytes_billed`; loads are batch jobs only (never streaming); reports read the `rpt_*` tables only. In-app `/reports` page; Tableau guide in `docs/warehouse/tableau.md`. BigQuery ML deferred (ADR-0013 amendment).
- **Tools exposed as MCP servers:** read-only market data, RAG retriever and margin-call status on **Cloud Run** (private; only the desk agent may invoke — MM-128). Slack/ServiceNow MCP servers are local-only and never deployed. (Jira is this project's own dev-story tracker, not an agent-facing tool — see `docs/adr/0007`; it has no MCP server.)
- **Notifications:** Slack; on GCP, client notices go on WhatsApp (`CLIENT_NOTIFIER=whatsapp`, an in-process adapter behind the approval gate — never an MCP tool) and Slack carries internal traffic (`INTERNAL_NOTIFIER=slack`) — see `docs/gcp/adr/0016`. **Escalation incidents:** ServiceNow (see `docs/adr/0007` — scoped to the SLA-escalation path only). **Dev-story tracker:** Jira (`MM-#` tickets; unaffected by the ServiceNow decision). **Secrets:** Secret Manager on GCP (`SECRETS_SOURCE=gcp`); AWS Secrets Manager for the paused AWS stack.
- **CI/CD:** GitHub Actions + Docker Hub (Docker Hub stays the registry on GCP too; CI logs in to GCP keylessly via Workload Identity Federation — MM-100). **Quality:** SonarCloud + pytest-cov. **Security scanning:** CodeQL (SAST), Dependabot (dependency CVEs + fix PRs), secret scanning with push protection — see `docs/adr/0018`. **IaC:** Terraform.

## Commands (keep these current)

```bash
# Local stack
docker compose up -d          # Kafka/Redpanda, Chroma, app services

# Python
make test                     # all tests
make test-unit                # fast unit tests
make cov                      # coverage report (target >= 80%)
make lint                     # ruff + black --check + mypy
make fmt                      # auto-format

# Simulator
make simulate SCENARIO=price_shock   # inject a synthetic market event

# BigQuery warehouse (G7; PYTHONPATH=src, GCP_PROJECT_ID set, your gcloud ADC in warehouse_loaders)
python -m warehouse.backfill --list                    # the quarter chunks of the simulated book
python -m warehouse.backfill --chunk 2024-Q1 --dry-run # compute + size one chunk, load nothing
python -m warehouse.backfill --all                     # dims + all 21 chunks (idempotent; re-run replaces)
python -m warehouse.schemas --write                    # re-render infra/gcp/bigquery_schemas after a schema change
python -m warehouse.sp500 --refresh                    # re-snapshot the S&P 500 list (committed CSV)
```
> If a command here is wrong or missing, fix it in this file as part of your story.

## Project conventions

- **Language/runtime:** Python 3.11+ (backend), TypeScript/Next.js (frontend).
- **Validation:** Pydantic models at every external boundary (feeds, API, tool IO).
- **Structure (target):** `src/agents/`, `src/calc/`, `src/streaming/`, `src/rag/`, `src/api/`, `src/mcp_servers/` (named to avoid colliding with the third-party `mcp` SDK package this project also depends on), `src/persistence/`, `src/config/` (shared Pydantic settings — env locally; deployed secrets from AWS Secrets Manager or GCP Secret Manager, chosen by `SECRETS_SOURCE=env|aws|gcp` (MM-101); added in MM-9, migrated from Parameter Store in MM-102), `src/ports/` + `src/adapters/` (interfaces and their vendor adapters for dependencies with two implementations during the GCP move — LLM, embeddings, vector store, event bus, notifier; `adapters/factory.py` picks one per env flag; added in MM-102), `src/observability/` (OTel tracing config + Prometheus metrics; added in MM-92/real key MM-74), `src/governance/` (data catalog loader, LLM data-class filter, per-call lineage, SDP scan summary; G8, ADR-0015), `src/warehouse/` (BigQuery star schema, simulated-book backfill, live daily load, report queries; G7, ADR-0013), `tests/`, `infra/` (Terraform + Prometheus/Grafana provisioning), `frontend/`.
- **Errors:** fail loud in calc/agent code; never silently swallow. Events are processed **idempotently** (replaying the same event must not double-raise a call).
- **Logging:** structured JSON logs; every agent action is logged with a correlation id for the margin-call run.
- **Reads are authenticated and scoped (MM-106):** every GET endpoint except `/health`, `/ready`, `/metrics`, `/market-universe`, `/public/stats` and `/webhooks/whatsapp` (Meta's verification handshake — Meta can't sign in; it only echoes Meta's challenge when the verify token matches; MM-133) depends on `require_user` and reads through `user_session(identity)`; `tests/unit/test_rls.py` fails if a new GET skips this. On Postgres, row-level security (`persistence/db/rls.py` + migration `b7d2f4a8c613`) enforces the scope in the database; sessions without an explicit scope are internal jobs and run firm-wide.
- **Security:** `ci.yml` grants `GITHUB_TOKEN` only `contents: read`; a job needing more (e.g. `id-token: write`) requests it at job level. Never merge a Dependabot PR blind — build/lint/typecheck first and bundle follow-up fixes into one PR. A story must not leave new high/critical CodeQL or Dependabot alerts open. The CI `security` job (pip-audit, licences, gitleaks, Trivy, Checkov) must stay green; accept a finding only in `.checkov.yaml` / `.trivyignore` / `.gitleaks.toml`, with its reason.
- **Data governance (G8):** a new table, column or document folder needs an entry in `docs/data_catalog.yaml` (class + owner; confidential columns need an `llm` handling), or `test_data_catalog.py` fails. Never update or delete `audit_log` rows from app code (append-only; revoked in the DB).
- **Commits:** conventional commits + Jira key, e.g. `feat(calc): add VM computation [MM-12]`.

## Where to look

- `docs/ARCHITECTURE.md` — lifecycle, agent mesh, streaming, data flow.
- `docs/AGENTS.md` — each agent's responsibility, inputs, outputs, tools.
- `docs/AGENT_ORCHESTRATION_FAQ.md` — code vs. LLM breakdown per component, and why the real (live-feed) trigger path runs the identical agent trace as the simulator.
- `docs/DATA_SOURCES.md` — structured vs unstructured data map + free sources.
- `docs/ROADMAP.md` — phased plan, mapped to Jira epics/stories with DoD.
- `docs/PROGRESS.md` — **living handoff log; update at the end of every story.**
- `docs/adr/` — architecture decision records (the *why* behind choices).
- `docs/gcp/` — GCP migration track: `GCP_ROADMAP.md` (plan), `GCP_PROGRESS.md` (its own handoff log — GCP stories log there, not in `PROGRESS.md`), `adr/` (ADR-0008+).

## Handoff protocol

At the end of every story, append a handoff entry to `docs/PROGRESS.md` using the template there: **Done / Decisions / Changed / Known issues / Next step.** This is how the next session resumes without context loss. Treat it as part of the Definition of Done, not optional paperwork.
