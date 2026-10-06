# MarginMaestro

[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=AdarshMurali_MarginMaestro&metric=alert_status&token=4157367f77e322beb6d40f440ad64e2ea134188f)](https://sonarcloud.io/summary/new_code?id=AdarshMurali_MarginMaestro)
[![Coverage](https://sonarcloud.io/api/project_badges/measure?project=AdarshMurali_MarginMaestro&metric=coverage&token=4157367f77e322beb6d40f440ad64e2ea134188f)](https://sonarcloud.io/summary/new_code?id=AdarshMurali_MarginMaestro)

**An agentic, event-driven platform that automates the end-to-end margin call lifecycle — from market event to client notification, escalation, and audit — using LLM agent orchestration, a RAG pipeline over legal/policy documents, and a real-time streaming backbone.**

> Status: ✅ **Live on Google Cloud.** API, MCP servers and event consumers on Cloud Run; Cloud SQL Postgres + pgvector; Gemini on Vertex AI; the "Ask the Desk" ADK agent on Agent Platform; frontend on Vercel. The earlier AWS (EC2) + Azure SQL deployment is paused and scheduled for decommissioning (Phase G9). See [`docs/gcp/GCP_ROADMAP.md`](docs/gcp/GCP_ROADMAP.md) and [`docs/gcp/GCP_PROGRESS.md`](docs/gcp/GCP_PROGRESS.md) for the GCP track, [`docs/ROADMAP.md`](docs/ROADMAP.md) / [`docs/PROGRESS.md`](docs/PROGRESS.md) for the original phases.

---

## 🚀 Try the live demo

| | |
|---|---|
| **App** | **https://marginmaestro.vercel.app** |
| **API** | http://13.202.222.57:8000 ([`/health`](http://13.202.222.57:8000/health), [`/docs`](http://13.202.222.57:8000/docs) for the OpenAPI schema) |

Sign in at [`/login`](https://marginmaestro.vercel.app/login) with one of the seeded demo accounts (also the default values of `demo_approver_password` / `demo_manager_password` / `demo_analyst_password` / `demo_auditor_password` in [`src/config/settings.py`](src/config/settings.py) — nothing sensitive, these exist purely to gate the demo dashboard):

| Username | Password | Role | Can do |
|---|---|---|---|
| `approver` | `MarginMaestro!Approver1` | Approver | Approve / reject / adjust a margin call; respond to its SLA |
| `manager` | `MarginMaestro!Manager1` | Manager | Everything `approver` can, plus the required **second sign-off** on elite-tier counterparties |
| `analyst1` | `MarginMaestro!Analyst1` | Margin analyst (viewer) | Read-only, **own book only: CP-1 … CP-4** |
| `analyst2` | `MarginMaestro!Analyst1` | Margin analyst (viewer) | Read-only, **own book only: CP-5 … CP-8** |
| `auditor` | `MarginMaestro!Auditor1` | Auditor | Read-only, every counterparty incl. system-level audit rows |

Every page except the public landing page needs a login, and the backend scopes every read to the caller: on Postgres, **row-level security** in the database itself hides other analysts' counterparties (MM-106). The `approver`, `manager` and `auditor` see all counterparties.

> This is a portfolio demo running on the project owner's own Google Cloud/Slack/WhatsApp accounts — please don't script/load-test it. A handful of clicks is exactly what it's for.

### A five-minute walkthrough

1. **Simulate Event** — pick a counterparty and a market shock (e.g. a price move on one of the curated tickers) and fire it. This kicks off a real LangGraph run: exposure is recomputed, the counterparty's CSA is retrieved via RAG, and a breach is evaluated.
2. **Approvals & SLA** — if the shock breached the threshold, a margin call is now waiting here. Approve it as `approver` (elite-tier counterparties additionally need `manager`'s second sign-off before the client notice goes out).
3. Once approved, a real Slack message goes out and an SLA timer starts. Use **Simulate counterparty response** on the same tab to resolve it (met → a confirmation is posted back to Slack; left to expire → it escalates to a real ServiceNow incident).
4. **Agent Trace** — pick the run you just triggered and watch its full step-by-step lifecycle (every LangGraph node, in order, with real timestamps and outputs) as a horizontal timeline.
5. **Margin Calls** / **Positions & Exposure** — see the resulting call and updated exposure for that counterparty.

Prefer to watch it happen end-to-end without clicking? Clone the repo and run the same scenario the API itself uses for demos:

```bash
pip install -e ".[dev]"
python -m demo.run_demo --base-url http://13.202.222.57:8000
```

---

## Why this project exists

In capital markets, a **margin call** is the process of demanding additional collateral when market moves erode the coverage on a portfolio of derivatives, repo, or financed positions. The *call itself* is simple arithmetic — but everything around it is not: interpreting bespoke legal agreements (CSAs), reconciling disputed valuations, choosing which collateral to post, notifying the counterparty, chasing non-response, escalating, and keeping a defensible audit trail.

Historically this is done with **spreadsheets, email, and phone calls**, and it is dangerously blind to the future — firms can tell you today's call but struggle to anticipate tomorrow's, which is exactly what caused margin-driven blow-ups in 2008, March 2020, the 2022 UK LDI crisis, Archegos, and LME nickel.

**MarginMaestro** models the full lifecycle as a mesh of specialized AI agents coordinated by an orchestrator, reacting to market events in real time, grounding its decisions in the actual legal and policy documents via RAG, and keeping a human in the loop for the decisions that matter.

## What it demonstrates

- **Agent orchestration** — an orchestrator agent conducting specialist agents (event detection, calculation, CSA interpretation, dispute, collateral optimization, communication).
- **RAG pipeline** — retrieval over CSAs, margin policy, exception rules, escalation procedures, and historical dispute notes.
- **Real-time streaming** — a Kafka event backbone driving intraday, tick-level margin evaluation, with a pluggable real-vs-simulated market feed.
- **Production engineering** — containerized services, CI/CD with quality gates and code coverage, security scanning (CodeQL, Dependabot, secret scanning with push protection), IaC, secrets management, observability, and a full audit trail.
- **Human-in-the-loop** — approval gates (with a second sign-off for elite-tier counterparties) and SLA-driven escalation to a real ServiceNow incident, reflecting how regulated institutions actually operate.

## High-level architecture

- **[`docs/architecture/functional-lifecycle.svg`](docs/architecture/functional-lifecycle.svg)** — the margin-call lifecycle as actually implemented in the LangGraph orchestrator: every node from `compute_exposure` through approval, notification, and SLA/escalation, color-coded by CLAUDE.md's golden rule (deterministic code vs. LLM reasoning/RAG vs. hybrid vs. the human-approval gate).
- **[`docs/architecture/tech-architecture.svg`](docs/architecture/tech-architecture.svg)** — the original (pre-GCP) deployment, now paused: AWS (EC2 + Elastic IP, Secrets Manager, S3, IAM), Vercel, Azure SQL, the CI/CD pipeline, and the third-party integrations (OpenAI, Slack, ServiceNow), with a clearly separated box for what's local-dev-only (Kafka/Redpanda, OTel/Prometheus/Grafana) and not part of the live deployment.
- **[`docs/architecture/gcp-tech-architecture-blue.svg`](docs/architecture/gcp-tech-architecture-blue.svg)** and **[`gcp-tech-architecture-multicolor.svg`](docs/architecture/gcp-tech-architecture-multicolor.svg)** — the live Google Cloud architecture (the GCP track in [`docs/gcp/GCP_ROADMAP.md`](docs/gcp/GCP_ROADMAP.md)): Cloud Run services, Pub/Sub and Cloud Tasks, Gemini on Vertex AI with Agent Platform, Model Armor and Sensitive Data Protection, Cloud SQL + pgvector with row-level security, Dataplex (BigQuery is planned for Phase G7), the security/operations layer, WhatsApp/Slack/ServiceNow, and the GitHub Actions → Docker Hub → Cloud Run (keyless WIF) deploy path. Same diagram in two icon styles: Google Cloud's official blue product icons, and its official four-colour core/category icons. PNG copies sit alongside each SVG.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full written design, and [`docs/AGENT_ORCHESTRATION_FAQ.md`](docs/AGENT_ORCHESTRATION_FAQ.md) for which parts are deterministic code vs. LLM-driven, and what happens end-to-end when a real (not simulated) market move triggers a run.

## Tech stack

| Layer | Choice | Notes |
|---|---|---|
| Agent orchestration | **LangGraph** (margin-call workflow) + **Google ADK** (desk assistant) | Fixed, auditable state-graph for the lifecycle on Cloud Run; a conversational ADK agent on Agent Platform for analyst Q&A (ADR-0019) |
| LLM | **Gemini on Vertex AI** | Reasoning, retrieval and drafting only, never math; every call screened by **Model Armor** + in-code guardrails, with **Sensitive Data Protection** masking (OpenAI remains a supported fallback via `LLM_PROVIDER`) |
| Embeddings | **Vertex AI text embeddings** | Query/document embeddings share one model |
| RAG + relational store | **Cloud SQL Postgres + pgvector** | Positions, ratings, calls, audit log and RAG chunks in one database, with **row-level security** scoping every read to the analyst's counterparties; LangGraph checkpoints persisted here |
| Documents | **Cloud Storage** | CSA, policy, dispute and escalation documents (30-day retention, scanned by SDP) |
| Eventing | **Pub/Sub + Cloud Tasks + Cloud Scheduler** | Live price refresh, impact events, one SLA timer per call, the daily margin run |
| API | **FastAPI on Cloud Run** | Scales to zero; IAM database login; OIDC for internal callers |
| Frontend | **Next.js on Vercel** | Real-time ops dashboard and the "Ask the Desk" chat, git-linked to auto-deploy on push to `main` |
| Agent platform | **Vertex AI Agent Runtime** | The desk assistant: Sessions + Memory Bank, `min_instances=0`; evaluated with **Gen AI evaluation** in CI |
| Tool interface | **MCP servers on Cloud Run** | Read-only market data, CSA/policy search and margin-call status; private, invoked only by the desk agent |
| Notifications | **WhatsApp Cloud API + Slack** | Client notices on WhatsApp (approved template, signed webhook for replies and delivery status); Slack for internal approvals, alerts and escalations |
| Escalation | **ServiceNow** | Real incident opened when an SLA is breached (see ADR-0007) |
| Governance | **Dataplex catalog + Data Lineage + Cloud Audit Logs** | Every table and document family catalogued and classified; lineage per margin call; data-access audit logs; append-only audit trail |
| Observability | **Cloud Trace + Cloud Logging + Cloud Monitoring** | One trace per margin-call run; structured logs; incident alert |
| Dev-story tracker | **Jira** | `MM-#` tickets for this project's own development — not an agent-facing tool |
| Secrets/config | **Secret Manager** | One JSON secret per environment (`marginmaestro-<env>`) |
| CI/CD | **GitHub Actions + Docker Hub → Cloud Run** | Lint, test, coverage, quality gate, security scans, build, push, and keyless (WIF) deploy on every merge to `main` |
| Quality | **SonarCloud + pytest-cov** | Coverage + quality gate |
| Security scanning | **CodeQL, Dependabot, secret scanning, pip-audit, gitleaks, Trivy, Checkov** | SAST, dependency CVEs, leaked secrets, image and IaC misconfiguration — free alternatives to Checkmarx / Black Duck (see ADR-0018) |
| IaC | **Terraform** | `infra/gcp/` provisions the Google Cloud deployment (the original AWS stack lives in `infra/`) |

## Repository layout

```
MarginMaestro/
├── README.md
├── CLAUDE.md                 # Agent operating guide (read first, every session)
├── CONTRIBUTING.md
├── TESTING.md
├── .env.example
├── .gitignore
├── src/                       # Backend: agents, calc, streaming, rag, api, config, persistence
├── frontend/                  # Next.js dashboard (deployed to Vercel)
├── infra/                     # Terraform: gcp/ (live) + the original AWS stack, Prometheus/Grafana provisioning
└── docs/
    ├── ARCHITECTURE.md       # Lifecycle, agent mesh, streaming, data flow
    ├── AGENTS.md             # Each agent: responsibility, IO, tools
    ├── DATA_SOURCES.md       # Structured vs unstructured data map + free sources
    ├── ROADMAP.md            # Phased, Jira-ready plan (epics/stories/DoD)
    ├── PROGRESS.md           # Living handoff log — updated at end of every task
    ├── AGENT_ORCHESTRATION_FAQ.md  # Code vs. LLM breakdown; real vs. simulated trigger parity
    ├── architecture/         # Functional lifecycle + technical architecture diagrams (see above)
    └── adr/                  # Architecture Decision Records
        ├── 0001-record-architecture-decisions.md
        ├── 0002-agent-orchestration-langgraph.md
        ├── 0003-streaming-kafka-defer-flink.md
        ├── 0004-vector-store-chromadb.md
        ├── 0005-llm-for-reasoning-code-for-math.md
        ├── 0006-openai-embeddings.md
        └── 0007-servicenow-for-escalation.md
```

## Getting started (local)

The fastest way to see the app is the live demo above — this section is for running your own copy.

```bash
git clone https://github.com/AdarshMurali/MarginMaestro.git
cd MarginMaestro
cp .env.example .env        # fill in OPENAI_API_KEY at minimum; see file for the rest
pip install -e ".[dev]"

docker compose up -d sqlserver redpanda chroma   # skip the `app` service -- run the API locally instead, below
alembic upgrade head
python -m persistence.seed_users      # seeds approver / viewer / manager (see table above)
python -m persistence.batch_loader    # seeds counterparties, positions, CSA/RAG documents

uvicorn api.main:app --reload
```

Then, separately:

```bash
cd frontend
cp .env.example .env.local  # points at your local API + NextAuth config
npm install
npm run dev                 # http://localhost:3000
```

`make test` / `make lint` run the backend test suite and linters (see `CONTRIBUTING.md` for the full contributor workflow). Frontend checks: `npx tsc --noEmit` and `npx eslint .` from `frontend/`.

## Disclaimer

MarginMaestro is a **portfolio / proof-of-concept** project. It uses **free and synthetic data**, and its margin calculations (VM/IM/SIMM) are **directionally correct approximations for demonstration**, not production-grade risk models. It is not affiliated with any employer and uses no proprietary data.
