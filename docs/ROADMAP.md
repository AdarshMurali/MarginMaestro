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

## Phase 7 — Reconciliation & Collateral (Epic: MM-45)

> **Note (2026-08-01):** Reconciliation Agent and Collateral Optimizer are **standalone capabilities** this phase, confirmed with the user -- not wired into the live orchestrator graph. The live graph's `await_sla_response` only has `"met"`/`"breached"` outcomes today; a real dispute would be a third outcome, and wiring that in is deferred until it's worth the added complexity.

- **MM-46** Trade-diff engine (deterministic) for dispute detection.
- **MM-47** **Reconciliation Agent**: isolate breaks + draft rationale grounded in dispute-history RAG.
- **MM-48** **Collateral Optimizer**: cheapest-to-deliver selection respecting eligibility/haircuts.
- **MM-49** Tests for dispute isolation and optimizer correctness.

**Exit criteria:** disputes are detected + explained; collateral is selected optimally.

## Phase 8 — Frontend dashboard (Epic: MM-50)

> **Note (2026-08-02):** design pass completed before coding, per [[feedback_phase_workflow]]. Dark-only theme (charcoal-navy background, amber/gold brand accent, green/amber/red/blue status colors), Next.js + Tailwind + shadcn/ui + Tremor (charts) + Framer Motion (Agent Trace only), NextAuth Credentials provider with seeded Approver/Viewer demo accounts (no external auth vendor), typographic "MM" monogram logo/favicon (inline SVG, no external design asset). Six tabs: Home, Positions & Exposure, Margin Calls, Agent Trace, Approvals & SLA, Simulate Event. Tagline *"Stop reading documents. Start making decisions."* placed in header + near RAG-citation surfaces.

- **MM-51** Next.js app on Vercel; design system (Tailwind theme tokens, dark palette, shadcn setup, "MM" logo/favicon SVGs, typography incl. monospace for figures); connect to API via REST + WebSocket/SSE.
- **MM-52** Positions & exposure board (status lights) + live price chart.
- **MM-53** Margin-call feed + lifecycle status.
- **MM-54** **Agent activity / orchestration trace** (the showpiece).
- **MM-55** Approval control + SLA/escalation view.
- **MM-56** "Simulate event" panel to trigger the lifecycle live.
- **MM-57** Auth: NextAuth Credentials provider, seeded Approver/Viewer accounts (Azure SQL), role-gated approval actions.
- **MM-58** Home/overview page (KPI strip, live activity ticker, "Simulate an event" CTA) + nav shell + copywriting pass (tagline placement, empty states).

**Exit criteria:** a viewer can inject an event and watch the whole lifecycle unfold on screen.

## Phase 9 — MCP, observability, audit hardening (Epic: MM-EPIC-9)

> **Note (2026-08-03, extended 2026-08-05):** four stories added ahead of MM-90 at the user's request -- three prompted by a design discussion on human-in-the-loop scope and live use of the Exposure board, a fourth prompted by a direct question about whether rating downgrades are actually addressed. Real Jira ticket numbers assigned when each is actually started, per the phase-workflow protocol -- not yet created.

- **Two-person sign-off for elite/large counterparties.** Today every counterparty gets the same single-approver gate (MM-37). Add a per-counterparty tier flag (deterministic config, not an LLM judgment call, per golden rule 1) -- standard tier keeps today's single approval; elite/large tier requires a *second*, different approver after the first. New `manager` role (third seeded demo account, alongside `approver`/`viewer`) holds the second signature -- confirmed with the user over reusing the `approver` role with a same-person block, for a cleaner maker-checker story. Mechanically this is one more `interrupt()`-gated node in the existing orchestrator graph, conditionally routed to for elite counterparties -- no new pause/resume mechanism needed, just a second instance of the one that already exists. Worth surfacing *why* a client is elite right on the second-approval card (pulled via the existing CSA-RAG agent) so the manager isn't hunting for context. A disagreement between the two approvers (manager overturns the first approver) is a real signal worth routing into the existing Reconciliation Agent (MM-46/47) as a dispute, rather than just logging a plain rejection.
- **Counterparty margin-call history / relationship reporting.** Distinct from MM-91 below (which is a step-by-step *process* audit log) -- this is a business-facing rollup: how many margin calls a counterparty has had over a period (quarter/year), average size, breach rate, so a broker/fund manager can flag "this client had 12 calls last quarter, might be worth revisiting their strategy" at a review. The underlying data already exists (every run persists via the LangGraph checkpointer, already read per-counterparty by MM-53's feed) -- this is an aggregation/reporting layer on top of already-persisted data, not a new logging mechanism. Likely a new read endpoint (group existing runs by counterparty + date range) plus a "Client History" view, reachable from a counterparty's card on the Exposure board.
- **Exposure board performance -- cache and/or parallelize live price + CSA lookups.** `build_exposure_board` (MM-52) computes every counterparty sequentially, and prices aren't cached at all (only CSA terms are, per-process) -- a full board load re-fetches live prices for every ticker, for real, on every request, one counterparty after another. This is also the likely root cause of the CoinGecko `429`s seen live (found 2026-08-03): `CoinGeckoFeed` calls the public API with **no API key** (`market_feed.py`'s own docstring), which is subject to a stricter, undocumented anonymous rate limit -- CoinGecko's documented free "Demo" tier (100 calls/min, 10k calls/month) requires registering a free API key, which this project has never done. Whether the fix is an in-memory/Redis price cache, parallelizing the per-counterparty fetches, registering a free CoinGecko Demo key, or some combination -- deliberately undecided here; make that call when the story is actually worked.
- ~~**Wire `rating_triggers` into breach evaluation.**~~ **Done 2026-08-16** (see `docs/PROGRESS.md`'s handoff entry -- Jira ticket pending, jira MCP server unreachable this session, create under MM-EPIC-9 when available). Threaded structurally: `MarketEvent.new_rating_grade`, `event_agent.py` persists the downgrade to `RatingORM`, `csa_rag.py`/`rag/csa_corpus.py` extract/generate structured `RatingTrigger(below_grade, reduced_threshold)` pairs (concrete numbers now, not prose), `calc/breach.py::effective_threshold()` deterministically applies the worst fired trigger. Verified live against real S3/Chroma/OpenAI. Flagged as a distinct, more speculative follow-on if wanted later: *proactive* downgrade-based risk flagging (using a downgrade as a leading indicator before any threshold math changes at all) -- a genuinely different feature, and one of the few places an LLM judgment call would legitimately belong, unlike the deterministic trigger-threshold fix itself.

- **MM-90** Finalize MCP servers (market-data, rag-retriever, slack, jira) with clean schemas.
- **MM-91** Immutable audit log for every step + an audit view.
- **MM-92** OpenTelemetry traces (optional) + Prometheus/Grafana panel for agent activity.
- **MM-93** Resilience: retries, timeouts, dead-letter path for failed events.

**Exit criteria:** every run is fully audited and observable; failures degrade gracefully.

## Phase 10 — Deployment & Demo polish (Epic: MM-EPIC-10)

> **Note (2026-08-01):** deployment previously existed only as a single underspecified line (`MM-102`) here. Expanded into real stories below. **Deliberately hybrid-cloud**: everything moves to AWS *except* the relational store, which stays on **Azure SQL** — that's not a leftover, it's `CLAUDE.md`'s stack choice (Azure SQL free tier), unaffected by this phase. Compute platform itself is still an open decision (`infra/compute.tf` has sat deliberately empty since MM-8, per that story's own note) — MM-102 below is where it actually gets made.

- **MM-100** Curated demo scenarios (2–3 counterparties) + one-command demo script.
- **MM-101** README/architecture diagrams finalized; short demo GIF/video.
- **MM-102** Backend deploy to AWS via Terraform — compute platform decision (ECS Fargate / EC2 / App Runner / Lambda — `infra/compute.tf`'s deferred choice from MM-8), containers built by the existing CI pipeline (already pushes to Docker Hub), IAM role attached to `iac/iam.tf`'s existing least-privilege policy (also sitting unattached since MM-8).
- **MM-103** Frontend deploy to Vercel + custom domain, wired to the deployed backend's real URL (not localhost).
- **MM-104** Secrets end-to-end for real: AWS Parameter Store (provisioned MM-8, `ParameterStoreSource` implemented MM-9) actually exercised against the deployed compute environment for the first time — until now only unit-tested/local-env-var-sourced.

**Exit criteria:** the solution is live and reachable at a public URL; only the relational DB (Azure SQL) sits outside AWS.

## Phase 11 — OPTIONAL: streaming analytics (Epic: MM-EPIC-11)

> Only if you commit to a genuine windowed/stateful job (ADR-0003). Do not add Flink as a buzzword.

- **MM-110** Flink job: rolling realized-volatility windows per security → feed IM.
- **MM-111** (Optional) CEP pattern: "N consecutive X% drops in T minutes" → escalation trigger.

**Exit criteria:** a real windowed computation influences IM, justifying Flink in the stack.

## Phase 12 — OPTIONAL: Open-source Kubernetes deployment (Epic: MM-EPIC-12)

> Good-to-have stretch goal, added 2026-08-01. Proves the architecture isn't AWS-locked by running the same containers on **OKD** (the free, open-source upstream project OpenShift is built from) instead of AWS's managed compute — not Red Hat's hosted OpenShift, and not a generic unrelated k3s/minikube setup. Only pursue after Phase 10's AWS deployment is real and working; this is additive portability, not a replacement for it.

- **MM-120** Package the full stack for Kubernetes (Helm chart or raw manifests) — API, RAG store, relational DB connection, streaming, all services from Phase 10's container images.
- **MM-121** Stand up a free OKD cluster (local, e.g. via CRC/`oc cluster`, or a free-tier hosted option if one exists) and deploy the packaged stack to it.
- **MM-122** Verify the deployed-on-OKD instance runs the same end-to-end lifecycle as the AWS deployment (reuse MM-44's E2E scenario against this environment).

**Exit criteria:** the same solution runs unmodified (config-only differences) on an open-source Kubernetes distribution, demonstrating platform portability.

---

## Milestones for the resume story

1. **M1 (Phases 0–2):** production-grade skeleton + tested margin math. *"CI/CD, quality gates, deterministic financial core."*
2. **M2 (Phases 3–6):** grounded, event-driven, full lifecycle with notify + escalate. *"Agentic RAG + streaming + human-in-the-loop."*
3. **M3 (Phases 7–10):** reconciliation, optimization, live dashboard, deployed demo. *"End-to-end, deployed, demoable."*
4. **M4 (Phase 11, optional):** streaming analytics. *"Stateful stream processing with Flink."*
