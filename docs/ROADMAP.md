# MarginMaestro — Roadmap (Phased, Jira-ready)

Development proceeds **phase by phase**, one story at a time, each finished to the Definition of Done in `CONTRIBUTING.md` before the next begins. Each **phase = a Jira Epic**; each story below is a Jira story. Story keys use `MM-#`.

> **Numbering note:** Jira assigns keys sequentially as tickets are created, not per the gapped scheme originally sketched here. Phase 0 (MM-1–MM-9) and Phase 1 (MM-10–MM-15) keys below are real, created keys. Keys in later phases are still the original placeholder scheme and will be corrected to match reality as each phase's tickets are actually created in Jira.

**Sequencing principle:** always keep a working system. Build the deterministic core first (data → math), then grounding (RAG), then the event/stream, then orchestration, then the human-facing edges (notify/escalate/UI). Optional streaming-analytics (Flink) comes last, only if justified.

> Suggested labels per story: `backend`, `infra`, `agent`, `rag`, `streaming`, `frontend`, `test`, `docs`.

---

## Phase 0 — Foundations & CI/CD (Epic: MM-1)

Goal: an empty-but-production-grade skeleton — anything you build after this inherits quality gates.

- **MM-2** Scaffold project structure (`src/`, `tests/`, `infra/`, `frontend/`), `pyproject.toml`, `Makefile`.
- **MM-3** Pre-commit hooks: `ruff`, `black`, `mypy`. 
- **MM-4** Dockerize the API service (multi-stage build); `docker-compose` for local stack (Redpanda, ChromaDB, app).
- **MM-5** Minimal FastAPI app with `/health` and `/ready` endpoints + structured JSON logging + correlation-id middleware.
- **MM-6** GitHub Actions CI: install, lint, type-check, `pytest --cov`, build image, push to Docker Hub.
- **MM-7** SonarCloud integration: upload coverage, configure quality gate (fail < 80% coverage / new critical issues). Add coverage badge to README.
- **MM-8** Terraform skeleton for AWS (Parameter Store params, IAM least-privilege, placeholders for compute).
- **MM-9** Config loader reading env locally / AWS Parameter Store in deployed envs (Pydantic settings).

**Exit criteria:** green CI on an empty service, image on Docker Hub, quality gate live.

## Phase 1 — Data foundation (Epic: MM-10)

- **MM-11** Synthetic data generators (seeded, versioned): 8 counterparties (Faker), 1 portfolio each with 8-12 positions sampled from a curated 30-ticker real-securities universe, ratings, collateral inventory.
- **MM-12** Azure SQL schema + migrations (positions, ratings, collateral, audit, tickets) — local `azure-sql-edge` container for now (real Azure SQL free tier exhausted for the month), config-only swap later.
- **MM-13** Free price adapters (`yfinance` + CoinGecko) behind a `MarketFeed` interface.
- **MM-14** FRED adapter for rates/vol reference data.
- **MM-15** Daily batch loader for EOD/reference data (runs locally/CI for now; cloud scheduling deferred to Phase 10).

**Exit criteria:** databases populated from generators + free feeds; all adapters unit-tested with mocks.

**Securities universe (30 real tickers, decided 2026-07-25):** `AAPL`, `MSFT`, `GOOGL`, `AMZN`, `TSLA`, `NVDA`, `META`, `HPE`, `JPM`, `WFC`, `SPCX` (explicit picks); `PLTR`, `AMD`, `MU`, `SMCI`, `NFLX`, `INTC` (2026-buzzing); `SPY` (S&P 500 proxy); `XOM`, `JNJ`, `BRK-B`, `V`, `DIS` (sector rounding); `IEF`, `TLT`, `SHY` (Treasury bond ETFs — substitute for Indian G-Secs, which have no free API/ticker access); `BTC-USD`, `ETH-USD`, `SOL-USD`, `XRP-USD` (crypto).

## Phase 2 — Calculation engine (deterministic) (Epic: MM-16)

> The financial core. Pure code, no LLM. Exhaustively tested. Self-contained pure-Python library (`src/calc/`) — no DB reads, no RAG, no orchestrator; those get wired in Phase 5.

- **MM-17** MTM valuation from positions + prices.
- **MM-18** Variation Margin computation.
- **MM-19** Initial Margin (SIMM proxy) with documented methodology — asset-class risk weights (equity 15%, ETF 10%, Treasury ETF 2%, crypto 30%) scaled by a VIX multiplier (MM-14's `VIXCLS`).
- **MM-20** Threshold + MTA breach evaluation.
- **MM-21** Golden-value test suite (hand-computed expected values) → drive coverage.

**Exit criteria:** given a portfolio + prices + CSA terms, the engine returns a correct, tested call amount.

## Phase 3 — RAG pipeline (Epic: MM-22)

> Documents live in S3 (source of truth for citations + re-ingestion); embedded with OpenAI `text-embedding-3-small` (query and document embeddings must share one model — see ADR-0006, superseding ADR-0004's local-BGE decision); agent reasoning via OpenAI `gpt-4o-mini` (Ollama not viable on this dev machine). Corpus: 8 per-counterparty CSA docs + 1 shared margin policy doc (9 total) — only the document types Phase 3 actually consumes; exception rules/escalation procedures/dispute notes/SIMM methodology are built in the phases that consume them (6, 7).

- **MM-23** Assemble the demo document corpus (S3-backed): 8 seeded per-counterparty CSA docs + 1 shared margin policy doc.
- **MM-24** Ingestion: chunk + embed (OpenAI) + load ChromaDB with metadata.
- **MM-25** Retriever service (filter by counterparty + doc_type), exposed as an MCP tool.
- **MM-26** **CSA-RAG Agent**: return threshold/MTA/eligible collateral/haircuts with citations; parse to validated structured terms.
- **MM-27** RAG tests: retrieval precision on seeded questions; citation presence.

**Exit criteria:** "what are CP-7's CSA terms?" returns correct, cited, structured terms.

## Phase 4 — Streaming & Event Agent (Epic: MM-28)

- **MM-29** Kafka topics + producer/consumer wiring (Redpanda locally).
- **MM-30** **Market simulator** producer: scripted scenarios (price shock, vol spike, downgrade) → `market.prices`/`market.events`.
- **MM-31** **Event Agent**: consume, classify, map event → affected entities (curated universe); emit impact set with idempotency key.
- **MM-32** Live feed adapter path (`MARKET_FEED_MODE=live`) sharing the same topic.
- **MM-33** Streaming integration tests with `testcontainers`.

**Exit criteria:** injecting a synthetic shock produces an impact set on the stream, idempotently.

## Phase 5 — Orchestration core (Epic: MM-34)

- **MM-35** LangGraph state object + orchestrator skeleton.
- **MM-36** Wire the happy path: event → calc → CSA-RAG → breach evaluation → (no-call | proceed).
- **MM-37** **Human approval gate** node (pause/resume; approve/reject/adjust) + minimal approval endpoint. *(2026-08-01: ships now so a human can actually exercise this before Phase 8's UI exists; flagged as provisional -- revisit its design at Phase 8, or whenever else becomes relevant, and get explicit user approval before considering it closed/final.)*
- **MM-38** Idempotent run handling + per-run correlation id, with **persisted** (Azure SQL) LangGraph checkpointing -- an awaiting-approval run must survive a process restart, given `MARGIN_CALL_SLA_MINUTES` is long enough for that to matter.
- **MM-39** Orchestration tests: assert branch taken (breach vs no-breach, approve vs reject) with mocked LLM/tools.

**Exit criteria:** a synthetic event drives a full evaluate→breach→await-approval flow, tested.

## Phase 6 — Notify, SLA, Escalation (Epic: MM-40)

- **MM-41** **Communication Agent** drafts notice; Slack MCP tool sends after approval.
- **MM-42** SLA timer (`MARGIN_CALL_SLA_MINUTES`) with met/breached outcomes. *(2026-08-01: no real counterparty-facing response channel exists in this demo, so "met" is signaled via a provisional `POST /margin-calls/{thread_id}/respond` endpoint standing in for the counterparty -- same "ships now, revisit at Phase 8's UI or when a real signal source exists" pattern as MM-37's approval endpoint. Deadline re-checks go through `POST /margin-calls/{thread_id}/check-sla`, a no-op if called before the deadline -- there's no real scheduler calling it periodically yet.)*
- **MM-43** Escalation path: retrieve escalation procedure (RAG) → open a **ServiceNow** incident with full context.
- **MM-44** End-to-end scenario test: shock → call → Slack → SLA breach → ServiceNow incident.

**Exit criteria:** full lifecycle runs end to end on a synthetic scenario, with real Slack + ServiceNow (free accounts).

> **Note (2026-07-25, resolved 2026-08-01 by `docs/adr/0007`):** escalation logging targets ServiceNow (the user's free dev instance), not Jira — a better fit for a business/margin-call escalation than an engineering issue tracker. This is scoped narrowly to *this* escalation feature; Jira remains this project's own dev-story tracker (MM-# tickets) and is unaffected.

## Phase 7 — Reconciliation & Collateral (Epic: MM-EPIC-7)

- **MM-70** Trade-diff engine (deterministic) for dispute detection.
- **MM-71** **Reconciliation Agent**: isolate breaks + draft rationale grounded in dispute-history RAG.
- **MM-72** **Collateral Optimizer**: cheapest-to-deliver selection respecting eligibility/haircuts.
- **MM-73** Tests for dispute isolation and optimizer correctness.

**Exit criteria:** disputes are detected + explained; collateral is selected optimally.

## Phase 8 — Frontend dashboard (Epic: MM-EPIC-8)

- **MM-80** Next.js app on Vercel; connect to API via REST + WebSocket/SSE.
- **MM-81** Positions & exposure board (status lights) + live price chart.
- **MM-82** Margin-call feed + lifecycle status.
- **MM-83** **Agent activity / orchestration trace** (the showpiece).
- **MM-84** Approval control + SLA/escalation view.
- **MM-85** "Simulate event" panel to trigger the lifecycle live.
- **TBD** UI/UX design pass (visual design system, copy/tone/taglines) + user login & roles (e.g. Approver vs Viewer) — not yet scoped, to be planned when Phase 8 starts.

**Exit criteria:** a viewer can inject an event and watch the whole lifecycle unfold on screen.

## Phase 9 — MCP, observability, audit hardening (Epic: MM-EPIC-9)

- **MM-90** Finalize MCP servers (market-data, rag-retriever, slack, jira) with clean schemas.
- **MM-91** Immutable audit log for every step + an audit view.
- **MM-92** OpenTelemetry traces (optional) + Prometheus/Grafana panel for agent activity.
- **MM-93** Resilience: retries, timeouts, dead-letter path for failed events.

**Exit criteria:** every run is fully audited and observable; failures degrade gracefully.

## Phase 10 — Demo polish (Epic: MM-EPIC-10)

- **MM-100** Curated demo scenarios (2–3 counterparties) + one-command demo script.
- **MM-101** README/architecture diagrams finalized; short demo GIF/video.
- **MM-102** Deploy: frontend to Vercel + custom domain; backend on AWS via Terraform.

## Phase 11 — OPTIONAL: streaming analytics (Epic: MM-EPIC-11)

> Only if you commit to a genuine windowed/stateful job (ADR-0003). Do not add Flink as a buzzword.

- **MM-110** Flink job: rolling realized-volatility windows per security → feed IM.
- **MM-111** (Optional) CEP pattern: "N consecutive X% drops in T minutes" → escalation trigger.

**Exit criteria:** a real windowed computation influences IM, justifying Flink in the stack.

---

## Milestones for the resume story

1. **M1 (Phases 0–2):** production-grade skeleton + tested margin math. *"CI/CD, quality gates, deterministic financial core."*
2. **M2 (Phases 3–6):** grounded, event-driven, full lifecycle with notify + escalate. *"Agentic RAG + streaming + human-in-the-loop."*
3. **M3 (Phases 7–10):** reconciliation, optimization, live dashboard, deployed demo. *"End-to-end, deployed, demoable."*
4. **M4 (Phase 11, optional):** streaming analytics. *"Stateful stream processing with Flink."*
