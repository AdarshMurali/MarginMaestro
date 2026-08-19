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

## Phase 9 — MCP, observability, audit hardening (Epic: MM-67)

> **Note (2026-08-03, extended 2026-08-05):** four stories added ahead of MM-90 at the user's request -- three prompted by a design discussion on human-in-the-loop scope and live use of the Exposure board, a fourth prompted by a direct question about whether rating downgrades are actually addressed. Real Jira ticket numbers assigned when each is actually started, per the phase-workflow protocol -- epic created 2026-08-17 as **MM-67**; individual stories get their own key when started (MM-68 is the first, see below).

- ~~**Two-person sign-off for elite/large counterparties.**~~ **Done 2026-08-17, MM-70.** Every counterparty gets a `tier` field (`CounterpartyTier`, migration `68237454ede4`; CP-1/CP-5 curated as elite) -- standard tier keeps today's single-approver gate (MM-37) unchanged; elite tier routes to a second `interrupt()` node (`await_manager_approval`) after an approved/adjusted first decision. New `manager` role (third seeded demo account) holds the second signature, gated by a new `require_manager` dependency. Same-person block enforced at the API layer (`POST /margin-calls/{thread_id}/manager-approve` 403s if the manager's username matches the first approver's, read from the run's persisted state, before ever resuming the graph). A manager rejection overturns the first approver's decision -- recorded as a distinct `approval_decision="disputed"` terminal state, not silently downgraded to `"rejected"`. **Deviated from this note's original plan:** did NOT route disagreements into the Reconciliation Agent (MM-46/47) -- investigated it first and found its real API (`reconcile_call(our_positions, counterparty_positions, ...)`) operates on trade-level position breaks, not human approval decisions; forcing a fit would have meant fabricating fake position-break data. A distinct terminal state + structured log is the honest fix. Frontend (elite badge, manager login, second-approval card) deliberately out of scope for this story -- backend/API only, verified live via direct HTTP calls; same pattern as MM-56/MM-68/MM-69.
- ~~**Counterparty margin-call history / relationship reporting.**~~ **Done 2026-08-17, MM-71.** New `GET /counterparties/{counterparty_id}/history?days=N` -- total calls, breached calls, breach rate, average call size over the trailing N days (all-time if omitted), distinct from MM-63's raw per-counterparty list. Pure aggregation over `api/margin_calls.py`'s existing `_all_summaries` (no new persistence). Excludes `EVALUATING`-status runs from the denominator (a resolved-outcomes-only rollup). 404s for an unknown counterparty, distinct from a real counterparty with zero calls (sane zero-rate response, no division error). Verified live against real dev-DB data, cross-checked against an independent manual computation over the raw list -- matched exactly. Frontend (a "Client History" view) deliberately out of scope -- backend/API only, same pattern as MM-68/69/70.
- ~~**Exposure board performance -- cache and/or parallelize live price + CSA lookups.**~~ **Partially resolved as of 2026-08-07 (MM-59/60/66, before this bullet was written down) + 2026-08-17 (MM-69).** The caching/N+1 half was already done: `build_exposure_board`, `get_counterparty_exposure`, and `/prices/{ticker}/history` are all SQL-only now (MM-59) -- no live price calls remain in any read path. The CoinGecko `429` half: `market_feed.py` gained `_get_with_retry()` (exponential backoff, honors `Retry-After`), wired into `CoinGeckoFeed`/`_coingecko_history` -- covers the three remaining live-call sites (`batch_loader.py`'s historical backfill, `live_feed_poller.py`, `POST /simulate`'s baseline price). **Not done:** registering a free CoinGecko Demo API key -- user chose retry/backoff only for this story; revisit if 429s still recur in practice.
- ~~**Wire `rating_triggers` into breach evaluation.**~~ **Done 2026-08-16, MM-68** (see `docs/PROGRESS.md`'s handoff entry). Threaded structurally: `MarketEvent.new_rating_grade`, `event_agent.py` persists the downgrade to `RatingORM`, `csa_rag.py`/`rag/csa_corpus.py` extract/generate structured `RatingTrigger(below_grade, reduced_threshold)` pairs (concrete numbers now, not prose), `calc/breach.py::effective_threshold()` deterministically applies the worst fired trigger. Verified live against real S3/Chroma/OpenAI. Flagged as a distinct, more speculative follow-on if wanted later: *proactive* downgrade-based risk flagging (using a downgrade as a leading indicator before any threshold math changes at all) -- a genuinely different feature, and one of the few places an LLM judgment call would legitimately belong, unlike the deterministic trigger-threshold fix itself.

- ~~**MM-90** Finalize MCP servers (market-data, rag-retriever, slack, jira) with clean schemas.~~ **Done 2026-08-18, MM-72** (real Jira key -- MM-90 in this note was always just placeholder numbering, per the phase-workflow protocol). This line predated ADR-0007 (accepted 2026-08-01) and was never updated after -- corrected scope on pickup: no Jira MCP server (ADR-0007 explicitly keeps Jira as this project's own dev-story tracker only, not agent-facing; `docs/AGENTS.md`'s tool matrix already only ever named `servicenow`, never `jira`). Built the missing `market_data.py` (Event Agent's own spec named this tool but it never existed). Hardened all four servers (`market_data`, `rag_retriever`, `slack_notifier`, `servicenow`): `Annotated[..., Field(description=...)]` on every tool parameter for richer MCP-client-visible schemas, docstrings documenting every domain exception each tool can raise, and real error-path tests confirming those exceptions propagate rather than get silently swallowed (CLAUDE.md golden rule: fail loud). `CLAUDE.md`'s MCP-servers line and this line both corrected to match ADR-0007.
- ~~**MM-91** Immutable audit log for every step + an audit view.~~ **Done 2026-08-19, real key MM-73.** New `GET /margin-calls/{thread_id}/audit-log` reads a genuinely immutable, insert-only `audit_log` table (`AuditLogORM` already existed, scaffolded ahead of time, but was only ever written once by `persistence/batch_loader.py` -- the orchestrator itself never wrote to it). Deliberately separate from the existing checkpoint-derived `/trace` (MM-54), which stays unchanged. Found and fixed two real bugs during implementation/verification: (1) a genuine LangGraph concurrency race between the new audit writes and `AzureSQLSaver`'s own checkpoint writes against the same connection -- fixed by sharing one `threading.Lock` between them; (2) `correlation_id` alone isn't unique per run (`POST /simulate`'s fan-out shares one `correlation_id` across every counterparty one triggering event affects, by design) -- the audit endpoint initially leaked a sibling counterparty's events, caught live, fixed by keying on `(correlation_id, counterparty_id)` together (migration `7316c632b993`). See `docs/PROGRESS.md`'s handoff entry for full detail.
- ~~**MM-92** OpenTelemetry traces (optional) + Prometheus/Grafana panel for agent activity.~~ **Done 2026-08-19, real key MM-74.** Full scope (confirmed with the user): real OTel traces (one span per orchestrator lifecycle step) exported to a new `jaeger` container, a new `GET /metrics` Prometheus endpoint, and an auto-provisioned Grafana dashboard (6 panels) -- three new `docker-compose` services (`jaeger`, `prometheus`, `grafana`; Grafana on host port `3001`, not `3000`, which the frontend dev server already owns). New `src/observability/` package: `tracing.py` (`configure_tracing()`) and `metrics.py` (`observe_step()`, a single context manager recording both a trace span and Prometheus `Counter`/`Histogram` per step, plus business metrics for breach rate and approval decisions) -- wired into all 8 orchestrator lifecycle steps, using the same interrupt-safe wrapping pattern MM-91's audit log established (spans wrap only the post-resume work on `await_*` nodes, never the pause itself). Found and fixed a real bug during implementation: `configure_tracing()` was being called unconditionally at `api/main.py`'s module-import time, so every test file that imports the app triggered a real background OTLP export attempt against an unreachable Jaeger; fixed by moving it into a FastAPI `lifespan` hook, verified empirically that this project's universal `TestClient(app)`-without-`with` convention never triggers `lifespan` at all. Verified live end-to-end: a real breach+approval run produced real spans in Jaeger, real scraped metrics in Prometheus (target healthy), and the provisioned Grafana dashboard's exact panel queries returned real non-empty data straight from Prometheus's API.
- ~~**MM-93** Resilience: retries, timeouts, dead-letter path for failed events.~~ **Done 2026-08-19, real key MM-75.** Investigated first and found the real gap: `streaming/event_agent.py`'s Kafka consume loop had zero error handling -- an uncaught exception crashed the whole process *before* the offset was committed, so a poison message would be redelivered and crash it again forever, wedging every message behind it on that partition. Confirmed scope with the user: harden the Event Agent's consumer (the only real Kafka consumer loop in the codebase) rather than also adding retry to the orchestrator's Slack/ServiceNow calls. New `_handle_with_retry()` wraps `handle_message` with a bounded, uniform retry budget (3 attempts, exponential backoff 1s/2s, a fresh DB session per attempt); once exhausted, the message is published to a new `market.dead-letter` topic (new `DeadLetterEvent` schema: original topic/partition/offset/key/value + error details + attempt count) and the offset is still committed, so one bad message can no longer wedge the consumer. Timeouts were audited, not added speculatively -- every external call in this path already has an explicit one (`EventConsumer.poll` 1s, `EventProducer.flush` 10s, MM-69's CoinGecko backoff); the new retry budget itself is what bounds total time on one message. Verified live against real Redpanda: a genuinely malformed message followed by a real valid one, both run through the actual production code path -- observed 3 real retries with real backoff, the poison message landing on the dead-letter topic with the correct payload, and the valid message right behind it processed normally, proving the offset advances past a poison message instead of wedging.

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
