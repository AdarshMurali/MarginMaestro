# MarginMaestro — Agent Specifications

Each agent is a node in the LangGraph orchestration. This file is the contract for every agent: its responsibility, inputs, outputs, tools, and whether it uses the LLM. **Reminder:** LLM = reasoning only; all numeric work is deterministic code (ADR-0005).

Legend — **Type:** `code` (deterministic), `llm` (reasoning/RAG/drafting), `hybrid`.

---

## Orchestrator (supervisor)

- **Type:** hybrid (control logic in code; may use LLM only for ambiguous routing)
- **Responsibility:** Owns the run. Receives a triggering event, threads the shared run-state through the graph, sequences the specialist agents, handles retries/exceptions, enforces the human-approval gate, and drives the SLA/escalation branch.
- **Inputs:** validated event (from Event Agent), run configuration.
- **Outputs:** final run outcome (`no_call` | `call_issued` | `escalated`), full audit trail.
- **Tools:** none directly — coordinates others. Reads/writes run-state and audit log.
- **Key behaviours:** idempotent per event key; correlation id per run; deterministic branch decisions (breach?, approved?, SLA met?).

## 1. Event Agent (detection & impact mapping)

- **Type:** hybrid (stream consumption in code; entity/impact mapping may use LLM for news)
- **Responsibility:** Consume `market.prices` / `market.events` from Kafka. Classify the event and **map it to affected counterparties, portfolios, and securities** within the curated universe. Emit an impact set that starts a margin run.
- **Inputs:** Kafka event (tick, vol spike, downgrade, collateral drop, trade, news).
- **Outputs:** `{event_type, affected_entities[], securities[], timestamp, event_key}`.
- **Tools:** Kafka consumer; market-data MCP tool; (for news) RAG/entity lookup over the curated universe.
- **Notes:** For price/vol/rating events, mapping is deterministic table lookup. For *news* events, the LLM maps text → entities, but only within the fixed universe — no open-world resolution.

## 2. Calculation Agent (MTM / VM / IM)

- **Type:** **code (never LLM)**
- **Responsibility:** Revalue the affected portfolio and compute the margin requirement: **MTM → Variation Margin**, and **Initial Margin** via a SIMM proxy. Deterministic and exhaustively unit-tested.
- **Inputs:** affected portfolio/positions (Azure SQL), current prices, existing collateral held.
- **Outputs:** `{mtm, variation_margin, initial_margin, current_exposure}`.
- **Tools:** pricing/valuation functions (pure Python); DB reads.
- **Notes:** All expected values are hand-verified in tests. IM proxy is documented and directionally correct, not a certified SIMM engine.

## 3. CSA-RAG Agent (agreement interpretation)

- **Type:** llm (RAG)
- **Responsibility:** Retrieve and interpret the counterparty's CSA/client agreement and margin policy to return the terms that govern the call: **threshold, MTA, eligible collateral, haircuts, rating triggers**.
- **Inputs:** counterparty id, question.
- **Outputs:** `{threshold, mta, eligible_collateral[], haircuts{}, rating_triggers[], citations[]}`.
- **Tools:** RAG retriever MCP tool (ChromaDB, filtered by counterparty + doc_type).
- **Notes:** Every returned term carries a **citation** to the source chunk. Structured numeric terms are parsed out and validated (Pydantic) before the math uses them.

## 4. Reconciliation & Dispute Agent

- **Type:** hybrid (diff in code; rationale via LLM + RAG over dispute history)
- **Responsibility:** Compare our computed call against the counterparty's view. If they diverge beyond tolerance, **isolate the breaking trades/valuations** and draft a dispute rationale, retrieving similar past disputes to suggest a resolution.
- **Inputs:** our call, counterparty call (or simulated counterparty view), trade populations.
- **Outputs:** `{agreed: bool, break_items[], suggested_resolution, citations[]}`.
- **Tools:** trade-diff functions (code); RAG retriever over `historical dispute notes` + `exception rules`.
- **Notes:** The numeric diff is deterministic; the LLM only explains and suggests, grounded in retrieved precedent.

## 5. Collateral Optimizer

- **Type:** code (optimization solver; optional LLM for explanation)
- **Responsibility:** Select **cheapest-to-deliver** collateral from available inventory to meet the call, respecting eligibility, haircuts, and (later) balance-sheet cost — across CSAs where possible.
- **Inputs:** required amount, eligible collateral + haircuts (from CSA-RAG), collateral inventory.
- **Outputs:** `{proposed_collateral[], post_haircut_value, rationale}`.
- **Tools:** an optimization routine (LP/greedy for the demo); DB reads on inventory.
- **Notes:** The LLM never chooses collateral; it may narrate the choice for the UI.

## 6. Communication Agent

- **Type:** llm (drafting) + code (delivery)
- **Responsibility:** Draft the client-facing margin-call notice and, **after human approval**, deliver it via Slack. Also drafts dispute and escalation messages.
- **Inputs:** approved call details (amount, reason, collateral, deadline).
- **Outputs:** notice text; Slack delivery receipt.
- **Tools:** Slack MCP tool.
- **Notes:** Never sends before the approval gate. Message content is drafted by the LLM; the send is deterministic code.

## Human-in-the-loop (approval gate)

- **Not an agent — a graph gate.** Between decision and notification, the run pauses for human `approve | reject | adjust`. Reflected in the dashboard. No client-facing call is sent autonomously.

## SLA & Escalation (orchestrator-driven)

- **Type:** code + RAG for procedure
- **Responsibility:** After notification, run the SLA timer (`MARGIN_CALL_SLA_MINUTES`). If the call is met, record and close. If not, follow the **escalation-procedures** document (retrieved via RAG) and open a **ServiceNow** incident with full context.
- **Tools:** timer (code); RAG retriever (escalation procedures); ServiceNow MCP tool.
- **Note:** ServiceNow (not Jira) for this escalation path only, per `docs/adr/0007`; Jira remains the dev-story tracker (MM-# tickets) and is unaffected.

## Audit (cross-cutting)

- **Type:** code
- **Responsibility:** Persist every lifecycle step to the immutable audit table with the run correlation id. Not skippable.

---

## Agent → tool → data matrix

| Agent | LLM? | MCP tools | Data read |
|---|---|---|---|
| Orchestrator | routing only | — | run-state, audit |
| Event | news only | market-data, rag | Kafka, universe map |
| Calculation | **no** | — | positions, prices, collateral (SQL) |
| CSA-RAG | yes | rag-retriever | ChromaDB (CSA/policy) |
| Reconciliation | rationale only | rag-retriever | trades (SQL), dispute notes (Chroma) |
| Collateral Optimizer | narration only | — | inventory (SQL), CSA terms |
| Communication | drafting | slack | approved call |
| SLA/Escalation | procedure only | rag-retriever, servicenow | escalation docs (Chroma) |
| Audit | no | — | writes audit (SQL) |
