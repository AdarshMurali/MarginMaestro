# MarginMaestro

[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=AdarshMurali_MarginMaestro&metric=alert_status&token=4157367f77e322beb6d40f440ad64e2ea134188f)](https://sonarcloud.io/summary/new_code?id=AdarshMurali_MarginMaestro)
[![Coverage](https://sonarcloud.io/api/project_badges/measure?project=AdarshMurali_MarginMaestro&metric=coverage&token=4157367f77e322beb6d40f440ad64e2ea134188f)](https://sonarcloud.io/summary/new_code?id=AdarshMurali_MarginMaestro)

**An agentic, event-driven platform that automates the end-to-end margin call lifecycle — from market event to client notification, escalation, and audit — using LLM agent orchestration, a RAG pipeline over legal/policy documents, and a real-time streaming backbone.**

> Status: ✅ **Live and deployed.** Backend on AWS (EC2 + Elastic IP), frontend on Vercel, relational store on Azure SQL. See [`docs/ROADMAP.md`](docs/ROADMAP.md) for the phased plan and [`docs/PROGRESS.md`](docs/PROGRESS.md) for current state.

---

## 🚀 Try the live demo

| | |
|---|---|
| **App** | **https://marginmaestro.vercel.app** |
| **API** | http://13.202.222.57:8000 ([`/health`](http://13.202.222.57:8000/health), [`/docs`](http://13.202.222.57:8000/docs) for the OpenAPI schema) |

Sign in at [`/login`](https://marginmaestro.vercel.app/login) with one of the seeded demo accounts (also the default values of `demo_approver_password` / `demo_viewer_password` / `demo_manager_password` in [`src/config/settings.py`](src/config/settings.py) — nothing sensitive, these exist purely to gate the demo dashboard):

| Username | Password | Role | Can do |
|---|---|---|---|
| `approver` | `MarginMaestro!Approver1` | Approver | Approve / reject / adjust a margin call; respond to its SLA |
| `manager` | `MarginMaestro!Manager1` | Manager | Everything `approver` can, plus the required **second sign-off** on elite-tier counterparties |
| `viewer` | `MarginMaestro!Viewer1` | Viewer | Read-only — browse every page, trigger nothing |

> This is a portfolio demo running on the project owner's own AWS/OpenAI/Slack accounts — please don't script/load-test it. A handful of clicks is exactly what it's for.

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
- **Production engineering** — containerized services, CI/CD with quality gates and code coverage, IaC, secrets management, observability, and a full audit trail.
- **Human-in-the-loop** — approval gates (with a second sign-off for elite-tier counterparties) and SLA-driven escalation to a real ServiceNow incident, reflecting how regulated institutions actually operate.

## High-level architecture

- **[`docs/architecture/functional-lifecycle.svg`](docs/architecture/functional-lifecycle.svg)** — the margin-call lifecycle as actually implemented in the LangGraph orchestrator: every node from `compute_exposure` through approval, notification, and SLA/escalation, color-coded by CLAUDE.md's golden rule (deterministic code vs. LLM reasoning/RAG vs. hybrid vs. the human-approval gate).
- **[`docs/architecture/tech-architecture.svg`](docs/architecture/tech-architecture.svg)** — the real, currently-deployed infrastructure: AWS (EC2 + Elastic IP, Secrets Manager, S3, IAM), Vercel, Azure SQL, the CI/CD pipeline, and the third-party integrations (OpenAI, Slack, ServiceNow), with a clearly separated box for what's local-dev-only (Kafka/Redpanda, OTel/Prometheus/Grafana) and not part of the live deployment.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full written design.

## Tech stack

| Layer | Choice | Notes |
|---|---|---|
| Agent orchestration | **LangGraph** | Explicit, auditable state-graph over agents |
| LLM | **OpenAI `gpt-4o-mini`** | Usage-minimized; LLM used for *reasoning, retrieval, and drafting only*, never math (`LLM_PROVIDER=ollama` remains supported for anyone running on hardware where local inference is viable) |
| Embeddings | **OpenAI `text-embedding-3-small`** | Query/document embeddings share one model |
| RAG vector store | **ChromaDB** | Runs as a container alongside the API on the same EC2 instance |
| Relational store | **Azure SQL** | Positions, ratings, audit log, users — the one piece deliberately kept outside AWS |
| Streaming | **Kafka (Redpanda locally)** | Event backbone for the intended design; not part of the current live deployment (see the tech architecture diagram above) |
| API | **FastAPI** | Async, auto OpenAPI, MCP-friendly |
| Frontend | **Next.js on Vercel** | Real-time ops dashboard, git-linked to auto-deploy on push to `main` |
| Tool interface | **MCP servers** | Market data, Slack, ServiceNow, RAG retriever exposed as MCP tools |
| Notifications | **Slack API** | Client margin-call notices + SLA-met confirmations |
| Escalation | **ServiceNow** | Real incident opened when an SLA is breached (see ADR-0007) |
| Dev-story tracker | **Jira** | `MM-#` tickets for this project's own development — not an agent-facing tool |
| Secrets/config | **AWS Secrets Manager** | One JSON secret per environment (`marginmaestro/<env>`); AWS Parameter Store remains available for non-secret config |
| Compute | **AWS EC2 + Elastic IP** | Single instance running the API + ChromaDB via Docker Compose; admin access via SSM Session Manager, no SSH |
| CI/CD | **GitHub Actions + Docker Hub** | Lint, test, coverage, quality gate, build, push |
| Quality | **SonarCloud + pytest-cov** | Coverage + quality gate |
| IaC | **Terraform** | AWS resources provisioned as code |

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
├── infra/                     # Terraform (AWS) + Prometheus/Grafana provisioning
└── docs/
    ├── ARCHITECTURE.md       # Lifecycle, agent mesh, streaming, data flow
    ├── AGENTS.md             # Each agent: responsibility, IO, tools
    ├── DATA_SOURCES.md       # Structured vs unstructured data map + free sources
    ├── ROADMAP.md            # Phased, Jira-ready plan (epics/stories/DoD)
    ├── PROGRESS.md           # Living handoff log — updated at end of every task
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
