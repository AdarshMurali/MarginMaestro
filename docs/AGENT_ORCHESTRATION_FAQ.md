# MarginMaestro — Agent Orchestration FAQ

> Companion to [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) and [`docs/AGENTS.md`](AGENTS.md). Those documents specify each agent's contract; this one answers the questions people actually ask when evaluating the project — *which parts are pure code, which parts genuinely need an LLM, and what happens when a real market move (not a simulated one) hits the system.*

---

## 1. What's deterministic Python vs. what's agent-driven

Per the golden rule in `CLAUDE.md` and ADR-0005 (**LLM for reasoning, code for math**):

| Component | Type | Why |
|---|---|---|
| **Calculation Agent** (MTM → VM, IM/SIMM proxy) | **code — never LLM** | Numbers must be exact and hand-verified. Exhaustively unit-tested. |
| **Reconciliation diff** (our call vs. counterparty's) | code | Deterministic comparison of two numbers/trade sets. |
| **Collateral Optimizer** selection | code (LP/greedy solver) | Cheapest-to-deliver is an optimization problem, not a judgment call. |
| **Breach evaluation, SLA timer, idempotency, audit logging** | code | Orchestrator control-flow — fixed branches, not reasoning. |
| **Communication delivery** (the actual Slack send) | code | Happens only after human approval; sending is mechanical. |
| **Price ingestion** (`market_feed.py`, `live_feed_poller.py`) | code | Pulling a quote from yfinance/CoinGecko is not a reasoning task. |
| **Event Agent** — price/vol/rating events | code | Deterministic table lookup: ticker → affected counterparties/portfolios (curated universe). |
| **Event Agent** — *news* events only | **LLM** | Free text → which curated-universe entities are affected. The only place the Event Agent reasons. |
| **CSA-RAG Agent** | **LLM (RAG)** | CSAs are bespoke legal prose — threshold, MTA, eligible collateral, haircuts must be *interpreted*, not looked up in a fixed schema. Every answer carries a citation. |
| **Reconciliation Agent — rationale** | **LLM (RAG)** | Explains *why* a dispute happened and suggests a resolution, grounded in retrieved precedent. The break itself is still a deterministic diff (see above). |
| **Communication Agent — drafting** | **LLM** | Writes the client-facing notice/escalation text. Never decides whether or when to send. |
| **SLA/Escalation — procedure lookup** | **LLM (RAG)** | Retrieves which escalation procedure applies from the policy document. The timer and the ServiceNow API call are code. |
| **Orchestrator** | mostly code | LangGraph state machine; LLM only for genuinely ambiguous routing (rare, per `docs/AGENTS.md`). |

Full agent → tool → data matrix: `docs/AGENTS.md` §"Agent → tool → data matrix".

## 2. Where does the agent actually make a call?

Only in places where the input is **unstructured and judgment-dependent**, never where it's numeric:

1. **CSA-RAG Agent** — turning a counterparty's actual legal agreement text into structured, usable terms. This is the clearest case: there is no fixed schema for a CSA, and hardcoding per-counterparty parsing rules doesn't scale or generalize.
2. **Event Agent (news path only)** — mapping a news headline to affected entities *within the curated universe* (`MARKET_UNIVERSE`). Deliberately scoped, not open-world entity resolution.
3. **Reconciliation Agent** — drafting a dispute rationale grounded in retrieved historical disputes, so a human reviewing it has *context*, not just a number.
4. **Communication Agent** — drafting readable, situation-appropriate client/escalation copy.
5. **SLA/Escalation** — picking the right escalation procedure out of policy documents that may vary by counterparty tier or breach type.

Everywhere else (the exposure math, the breach test, collateral choice, the send, the timer) is intentionally boring, deterministic code — because getting a margin number wrong is the one failure mode this system cannot tolerate.

## 3. Why this couldn't have been "just a pipeline" (no agent orchestration)

A plain deterministic pipeline works fine for the math — and MarginMaestro *does* keep the math as a plain pipeline. What it can't do with fixed code paths is:

- **Read bespoke legal documents.** Every counterparty's CSA is prose written by different lawyers at different times. A rules engine would need a bespoke parser per counterparty; RAG + LLM extraction generalizes across documents it has never seen a template for.
- **Explain a dispute in language a human can act on.** A human approver needs *why* two valuations diverge and what similar past disputes looked like — that's synthesis over unstructured history, not a lookup.
- **Draft situationally appropriate notifications.** Amount, counterparty tone, and urgency vary per call; templating covers the common case but degrades for edge cases an LLM naturally handles.
- **Do all of the above while staying auditable.** The orchestrator (LangGraph) makes every step — deterministic or LLM — an explicit, inspectable node with a logged output and citation, so "why did the system do X" is always answerable. A hand-rolled pipeline with an LLM call bolted on the side wouldn't give you that same per-step audit trail for free.

In short: the *agentic* part of the architecture earns its place specifically at the legal/document/communication boundary — not at the math, which stays deliberately non-agentic per ADR-0005.

## 4. The margin-call flow when a stock genuinely moves (not simulated)

**Who triggers the run:** nothing about the *trigger* is agent-driven — a price event on the `market.prices` Kafka topic is what starts everything, regardless of whether it came from the simulator or a real feed.

MarginMaestro already implements **both** producers behind one interface (`MarketFeed` protocol, `src/streaming/market_feed.py`):

- `SimulatedMarketFeed` — scripted moves, used for demos/tests (`MARKET_FEED_MODE=simulated`).
- `CompositeMarketFeed` — **real prices**: yfinance for equities/ETFs, CoinGecko for crypto (`MARKET_FEED_MODE=live`).

The live path (`src/streaming/live_feed_poller.py`, MM-59) polls on a fixed interval, independent of any API request — no endpoint ever calls a market-data provider directly. `src/streaming/live_feed_publisher.py` then **publishes onto the exact same `market.prices` topic, using the exact same `PriceQuote` schema** the simulator uses. The code comment there states the intent directly: *"so the Event Agent's classification logic needs no live-specific branch."*

So if a real counterparty's stock actually crashed:

1. **Poller** fetches the real yfinance/CoinGecko quote → publishes to `market.prices` (identical schema to a simulated tick).
2. **Event Agent** consumes it — same deterministic entity/portfolio mapping as any price event (LLM doesn't get involved; that's news-only).
3. **Calculation Agent** revalues MTM/VM/IM off the real price — same pure-Python code path.
4. **CSA-RAG Agent** pulls that counterparty's real threshold/MTA from ChromaDB.
5. **Breach?** → **Reconciliation** → **Collateral Optimizer** → **human approval gate** (nothing client-facing fires without this) → **Communication Agent** sends the real Slack notice → **SLA timer** → escalate to a real ServiceNow incident if missed → every step written to the immutable audit log.

**The full LangGraph agent trace runs step-by-step exactly as it does today in the demo.** The only difference between "simulated" and "real" is *which process produced the tick* — the orchestrator, every agent, and the approval/SLA/escalation machinery have no branch that distinguishes the two. This is a deliberate design choice (see `docs/ARCHITECTURE.md` §2, principle 7 — "pluggable feed"), not something that would need to be built later.
