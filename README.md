# MarginMaestro

[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=AdarshMurali_MarginMaestro&metric=alert_status&token=4157367f77e322beb6d40f440ad64e2ea134188f)](https://sonarcloud.io/summary/new_code?id=AdarshMurali_MarginMaestro)
[![Coverage](https://sonarcloud.io/api/project_badges/measure?project=AdarshMurali_MarginMaestro&metric=coverage&token=4157367f77e322beb6d40f440ad64e2ea134188f)](https://sonarcloud.io/summary/new_code?id=AdarshMurali_MarginMaestro)

**An agentic, event-driven platform that automates the end-to-end margin call lifecycle — from market event to client notification, escalation, and audit — using LLM agent orchestration, a RAG pipeline over legal/policy documents, and a real-time streaming backbone.**

> Status: 🚧 In active development (Phase 0 — foundations). See [`docs/ROADMAP.md`](docs/ROADMAP.md) for the phased plan and [`docs/PROGRESS.md`](docs/PROGRESS.md) for current state.

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
- **Human-in-the-loop** — approval gates and SLA-driven escalation, reflecting how regulated institutions actually operate.

## High-level architecture

```
Market feed / event  ──▶  Kafka  ──▶  Event Agent  ──▶  Orchestrator
(real or simulated)                                        │
                                                           ├─▶ Calculation Agent   (MTM, VM, IM — deterministic code)
                                                           ├─▶ CSA-RAG Agent        (thresholds, MTA, eligible collateral)
                                                           ├─▶ Reconciliation Agent (dispute detection & rationale)
                                                           ├─▶ Collateral Optimizer (cheapest-to-deliver)
                                                           └─▶ Communication Agent  (Slack notice, drafts)
                                                           │
                       Human approval ◀──────────────────┘
                                                           │
         Slack notify ─▶ SLA timer ─▶ met? ─┬─ yes ─▶ log & close
                                            └─ no  ─▶ escalate ─▶ Jira ticket
                                                           │
                                              Audit log (immutable, every step)
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full design.

## Tech stack

| Layer | Choice | Notes |
|---|---|---|
| Agent orchestration | **LangGraph** | Explicit, auditable state-graph over agents |
| LLM | **Local (Ollama) for dev; OpenAI `gpt-4o-mini` optional** | Cost-controlled; LLM used for *reasoning only*, never math |
| Embeddings | **Local (sentence-transformers / BGE)** | Free; no per-call cost |
| RAG vector store | **ChromaDB** | Free, container-friendly |
| Relational store | **Azure SQL (free tier)** | Positions, ratings, audit log, ticket state |
| Streaming | **Kafka (Redpanda locally)** | Event backbone; Flink deferred (see ADR-0003) |
| API | **FastAPI** | Async, auto OpenAPI, MCP-friendly |
| Frontend | **Next.js on Vercel** | Real-time ops dashboard |
| Tool interface | **MCP servers** | Market data, Jira, Slack, RAG retriever exposed as MCP tools |
| Notifications | **Slack API** | Client margin-call notices |
| Ticketing | **Jira (free)** | Escalations + development stories/evidence |
| Secrets/config | **AWS Parameter Store** | SecureString for secrets (free tier) |
| CI/CD | **GitHub Actions + Docker Hub** | Build, test, scan, deploy |
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
└── docs/
    ├── ARCHITECTURE.md       # Lifecycle, agent mesh, streaming, data flow
    ├── AGENTS.md             # Each agent: responsibility, IO, tools
    ├── DATA_SOURCES.md       # Structured vs unstructured data map + free sources
    ├── ROADMAP.md            # Phased, Jira-ready plan (epics/stories/DoD)
    ├── PROGRESS.md           # Living handoff log — updated at end of every task
    └── adr/                  # Architecture Decision Records
        ├── 0001-record-architecture-decisions.md
        ├── 0002-agent-orchestration-langgraph.md
        ├── 0003-streaming-kafka-defer-flink.md
        ├── 0004-vector-store-chromadb.md
        └── 0005-llm-for-reasoning-code-for-math.md
```

## Getting started

> Full setup lands in Phase 0. For now this repo holds the design docs that drive development.

```bash
# (coming in Phase 0)
cp .env.example .env
docker compose up -d
```

## Disclaimer

MarginMaestro is a **portfolio / proof-of-concept** project. It uses **free and synthetic data**, and its margin calculations (VM/IM/SIMM) are **directionally correct approximations for demonstration**, not production-grade risk models. It is not affiliated with any employer and uses no proprietary data.
