# MarginMaestro — Architecture

This document describes the system design: the margin-call lifecycle, the event triggers, the agent mesh and orchestration, the streaming backbone, the data flows, and the cross-cutting concerns (security, observability, audit).

---

## 1. Problem framing

A **margin call** demands additional collateral when market moves erode the coverage on a portfolio of derivatives / repo / financed positions. The mechanics:

- **Variation Margin (VM)** covers the change in mark-to-market since the last exchange.
- **Initial Margin (IM)** covers *potential future exposure*; under UMR it is modelled (ISDA SIMM). IM rises with volatility.
- A call is issued when exposure exceeds the **threshold + Minimum Transfer Amount (MTA)** defined in the counterparty's **Credit Support Annex (CSA)**.

The hard parts are not the arithmetic — they are interpreting bespoke legal agreements, reconciling disputes, choosing collateral, notifying and chasing counterparties, escalating, and staying auditable. MarginMaestro automates that workflow and, crucially, reacts to market events **in real time**.

## 2. Design principles

1. **Event-driven.** Prices move during market hours; the system reacts to a stream of market events rather than running a single nightly batch.
2. **Agentic with an orchestrator.** A supervisor agent decomposes the workflow and dispatches specialist agents; it owns sequencing, exceptions, and escalation.
3. **LLM for reasoning, code for math.** Numbers are deterministic and tested; the LLM reasons over documents, disputes, and language. (ADR-0005.)
4. **Grounded in documents (RAG).** CSA terms, policy, exceptions, escalation rules, and past disputes are retrieved, not hardcoded.
5. **Human-in-the-loop.** A client-facing call always passes an approval gate; escalation follows documented procedures.
6. **Auditable by construction.** Every step of every run is logged immutably with a correlation id.
7. **Pluggable feed.** The market source is an interface with two implementations — a synthetic simulator and a live free-data adapter — behind one contract.

## 3. Margin-call lifecycle (end to end)

```
(1) Market event            e.g. price tick / vol spike / rating downgrade / synthetic shock
        │
        ▼
(2) Event detection         Event Agent consumes Kafka, maps event → affected
    & impact mapping        counterparties / portfolios / securities (curated universe)
        │
        ▼
(3) Revalue & compute       Calculation Agent (deterministic): MTM → VM, IM (SIMM proxy)
        │
        ▼
(4) Apply CSA terms         CSA-RAG Agent: threshold, MTA, eligible collateral, haircuts
        │
        ▼
(5) Breach?  ── no ──▶ log "evaluated, no call"  (close run)
        │ yes
        ▼
(6) Reconciliation          Reconciliation Agent: compare vs counterparty view;
    & dispute check         if divergent, isolate breaking trades + draft rationale
        │
        ▼
(7) Collateral selection    Collateral Optimizer: cheapest-to-deliver from inventory
        │
        ▼
(8) HUMAN APPROVAL GATE      approve / reject / adjust  ◀── human-in-the-loop
        │ approved
        ▼
(9) Notify client           Communication Agent → Slack notice (drafted + sent)
        │
        ▼
(10) SLA timer              wait up to MARGIN_CALL_SLA_MINUTES
        │
        ├── met ─────▶ record collateral received → settle → close
        └── not met ─▶ (11) Escalate per escalation-procedures doc → open ServiceNow incident
        │
        ▼
(12) Audit                  every step above written to the immutable audit log
```

## 4. Event triggers

The system is driven by events. Supported trigger types (all can be produced by the simulator for demo/test):

| Trigger | Source | Effect |
|---|---|---|
| **Price move** | price tick stream | Recompute MTM → VM; may breach threshold |
| **Volatility spike** | derived (rolling window) | Recompute IM (SIMM proxy) upward |
| **Counterparty rating downgrade** | ratings event | Rating-based CSA trigger → extra collateral |
| **Collateral value drop** | price of posted collateral | Haircut/shortfall → top-up call |
| **Portfolio change** | new trade booked | Re-evaluate exposure |
| **Macro/news event** | news feed (curated) | Maps to affected entities → re-evaluate |

## 5. Agent mesh & orchestration

Orchestration is implemented with **LangGraph** — an explicit, inspectable state graph. Each node is an agent or a deterministic step; edges encode the control flow (including the breach branch and the approve/escalate branches). See `docs/AGENTS.md` for each agent's full contract.

```
                         ┌────────────────────────┐
                         │      ORCHESTRATOR       │  (LangGraph state machine)
                         │  owns run state, retries,│
                         │  branching, escalation   │
                         └───────────┬─────────────┘
        ┌──────────────┬─────────────┼──────────────┬───────────────┐
        ▼              ▼             ▼              ▼               ▼
 ┌────────────┐ ┌────────────┐ ┌───────────┐ ┌─────────────┐ ┌─────────────┐
 │   Event    │ │ Calculation│ │  CSA-RAG  │ │Reconciliation│ │  Collateral │
 │   Agent    │ │   Agent    │ │   Agent   │ │   Agent      │ │  Optimizer  │
 │(map impact)│ │(MTM/VM/IM) │ │(CSA terms)│ │(disputes)    │ │(CTD)        │
 └────────────┘ └────────────┘ └───────────┘ └─────────────┘ └─────────────┘
        │                                                          │
        └──────────────────────► Communication Agent ◀────────────┘
                                 (Slack notice, drafts)
```

- **Deterministic vs reasoning nodes.** Calculation and optimization nodes are pure code (tool calls to a solver). CSA-RAG, Reconciliation, and Communication nodes use the LLM for interpretation/drafting, grounded by retrieval.
- **State object.** A single typed run-state (correlation id, event, affected entities, computed exposure, CSA terms, decision, notification status, SLA deadline, audit entries) threads through the graph.
- **Idempotency.** Each event carries a key; re-processing the same key does not raise a duplicate call.

## 6. Streaming backbone

Prices/events are real-time during market hours, so the transport is a stream, not a batch.

```
Producer(s)                Kafka topics              Consumers
────────────               ────────────              ─────────
Market simulator  ──┐
  (scripted)        ├──▶  market.prices  ──▶  Event Agent (tick evaluation)
Live feed adapter ──┘                          │
  (yfinance/crypto)                            ├──▶ (optional) Flink job:
News/event injector ──▶  market.events  ──────┘      rolling realized-vol → IM
                                                     (deferred — ADR-0003)
Orchestrator      ──────▶  margin.calls   ──▶  Communication + audit consumers
```

- **Kafka (Redpanda locally)** is the event backbone — required. It decouples producers from the agent pipeline and gives replayability.
- **Batch vs stream:** *daily* reference data (e.g., EOD prices for backfill, ratings snapshots) is loaded by a scheduled job (EventBridge → Lambda). *Intraday* ticks flow through Kafka. Do not use streaming for daily-only data.
- **Flink is deferred (ADR-0003).** It is added only if a genuine windowed/stateful computation is built — the natural candidate is rolling **realized volatility → IM**, or CEP to detect "N consecutive drops in T minutes." Until then a plain Kafka consumer (or Faust) handles per-tick evaluation. Never add Flink as a buzzword.
- **Simulated vs live feed** implement one `MarketFeed` interface; `MARKET_FEED_MODE` selects. Tests and demos use the simulator for determinism.

## 7. RAG pipeline

Two data planes: **structured** (numbers → SQL, drives the math) and **unstructured** (documents → vector store, drives the reasoning). See `docs/DATA_SOURCES.md`.

```
Documents (CSA, margin policy, exception rules,      Query (e.g. "CSA terms for CP-7?")
escalation procedures, historical dispute notes,             │
SIMM methodology, collateral schedule)                       ▼
        │ ingest                                     Retriever (MCP tool)
        ▼                                                    │
  chunk + embed (local BGE)                                  ▼
        │                                             top-k chunks + citations
        ▼                                                    │
   ChromaDB (vectors + metadata:                             ▼
   counterparty, doc_type, effective_date)          CSA-RAG / Reconciliation Agent
                                                     grounds its answer + cites source
```

- Metadata filtering (by counterparty and doc type) keeps retrieval precise.
- Every RAG answer carries **citations** back to the source chunk — essential for a regulated, auditable workflow.
- The retriever is exposed as an **MCP tool** so any agent can call it uniformly.

## 8. Data flow summary

1. **Ingress:** ticks/events → Kafka. Reference data (positions, ratings, collateral inventory, CSAs) loaded to Azure SQL / Chroma.
2. **Processing:** Event Agent → Orchestrator → specialist agents; math from SQL data, terms from Chroma.
3. **Decision:** breach evaluation → human approval.
4. **Egress:** Slack notification; ServiceNow incident on escalation; audit log to SQL.
5. **Presentation:** FastAPI exposes state; Next.js dashboard streams updates (WebSocket/SSE).

## 9. Component / deployment view

```
┌────────────────────────── Vercel ──────────────────────────┐
│  Next.js dashboard  (positions, price charts, call feed,    │
│  agent trace, approval, SLA/escalation, simulate panel)     │
└───────────────▲─────────────────────────────────────────────┘
                │ WebSocket/SSE + REST
┌───────────────┴──────────── AWS (Terraform) ───────────────┐
│  FastAPI service  ── LangGraph orchestrator + agents         │
│  MCP servers: market-data | rag-retriever | slack | jira     │
│  Kafka/Redpanda  |  ChromaDB  |  simulator/feed adapter       │
│  Scheduler: EventBridge → Lambda (daily reference loads)     │
│  Config/secrets: AWS Parameter Store (SecureString)          │
│  Azure SQL (free tier): positions, ratings, audit, tickets   │
└──────────────────────────────────────────────────────────────┘
        │ Slack API           │ ServiceNow API     │ LLM (Ollama local / OpenAI)
        ▼                     ▼                    ▼
   client notices        escalations           reasoning only
```

All services are **containerized** (Docker), images pushed to **Docker Hub**, deployed via **GitHub Actions** CI/CD. Infra is provisioned with **Terraform**.

## 10. Cross-cutting concerns

**Security & secrets.** No secrets in code; all via AWS Parameter Store (SecureString) in deployed envs, `.env` locally. Least-privilege IAM for AWS resources. Slack/ServiceNow tokens scoped minimally.

**Observability.** Structured JSON logging with a per-run correlation id; every agent action logged. Health/readiness endpoints on the API. Optional OpenTelemetry traces + a Prometheus/Grafana panel to visualize agent activity.

**Audit trail.** Every lifecycle step (event → decision → notification → escalation) is written to an immutable audit table in Azure SQL. This is a first-class output, not an afterthought — it is what makes the workflow defensible.

**Resilience.** Retries + timeouts on external calls; a dead-letter path for failed events; idempotent event handling so replays are safe.

**Cost control.** Local LLM + local embeddings by default; OpenAI reserved for an optional "premium" run. Parameter Store (free) over Secrets Manager. Redpanda/Chroma run locally in containers. Vercel + free-tier data sources.

## 11. Non-functional targets (demo-scale)

- Curated universe: ~10–20 securities / a handful of counterparties.
- Tick evaluation latency: sub-second per event on the demo scale.
- Coverage: ≥ 80%, enforced in CI.
- Reproducible demo: one command injects a scenario and drives the full lifecycle.

## 12. Key decisions

See `docs/adr/` — orchestration (LangGraph), streaming (Kafka; defer Flink), vector store (ChromaDB), and the LLM-for-reasoning-code-for-math rule are all recorded there with rationale.
