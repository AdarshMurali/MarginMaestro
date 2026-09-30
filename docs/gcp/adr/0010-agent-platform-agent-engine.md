# ADR-0010: Host the LangGraph orchestrator on Vertex AI Agent Engine (Agent Platform)

- **Status:** Accepted (amended 2026-09-28: Agent Platform governance layer added)
- **Date:** 2026-09-28
- **Amends:** ADR-0002 (LangGraph stays the orchestration framework)

## Context

Google's Agent Platform offers a managed runtime (Vertex AI **Agent Engine**), the Agent Development Kit (ADK), managed sessions/memory, and built-in tracing and evaluation. The question is whether to adopt it and how deeply.

## Decision

- **Keep LangGraph** (ADR-0002). Agent Engine supports LangGraph agents natively, so the existing state graph, `interrupt()` approval gates and tests carry over.
- **Deploy the orchestrator graph to Agent Engine** as the managed agent runtime. The FastAPI API on Cloud Run calls it for `/simulate`, approvals and resumes.
- **Checkpointing** stays on this project's own database-neutral saver (`persistence/db/checkpoint_saver.py`, `SqlCheckpointSaver`), which runs unchanged on SQL Server and on Cloud SQL Postgres (ADR-0011), so human-approval pauses survive restarts. *Amended 2026-09-30 (MM-105, user decision):* LangGraph's official Postgres checkpointer was the original plan, but ours already works on Postgres — keeping it means one code path, Alembic-managed tables and the existing audit-write lock.
- **Evaluation:** use Vertex AI **Gen AI evaluation** for the golden scenario set (tool-call trajectory + grounding/citation checks), in CI on demand.
- **MCP servers** (market data, RAG retriever, Slack, WhatsApp, ServiceNow) run on Cloud Run and are called as tools by the agent.
- **Governance layer (amendment):** the agent runs with its own **Agent Identity** (not a shared service account), and every outbound call — MCP tools and Gemini — goes through **Agent Gateway**:
  - **IAM policies on the gateway:** deny by default; each agent is allowed only its named tools (e.g. the orchestrator may call `rag_retriever` and `market_data`, but only the Communication path may call `slack_notifier` / `whatsapp_notifier`).
  - **Model Armor on the gateway** screens prompts and tool responses (see ADR-0014).
  - **Semantic Governance Policies** enforce plain-language business rules at runtime, e.g. "never call a client notifier for a margin call without a recorded human approval".
  - Our MCP servers stay on Cloud Run and are registered behind the gateway.
- **Not adopted:**
  - Rewriting agents in **ADK** — a full rewrite for little gain; revisit only if a feature is ADK-only.
  - **RAG Engine** — paid default backend, and it can't apply our Postgres row-level security to retrieval (ADR-0011).
  - **Vector Search** — always-on endpoint billed even when idle; overkill for ~15 documents (ADR-0011).

## Rationale

Managed hosting, sessions and tracing without giving up a working, tested orchestration layer.

## Consequences

- Agent Engine is billed by runtime vCPU/memory-hours — **the second-largest post-trial cost risk** after Cloud SQL. Fallback (ADR-0017): run the same graph in-process inside the Cloud Run API (`AGENT_RUNTIME=cloudrun`), which is exactly how it runs today.
- Agent-side code must not assume local filesystem or process state between requests.
- Agent Gateway and Semantic Governance pricing is not fully published (Semantic Governance billing starts later in 2026). Confirm costs before enabling in G5; if they would breach the trial budget (ADR-0017), keep the in-code equivalents (tool allow-list in the graph, approval check before notifier calls) and document the gap.
- In-code controls stay regardless — they are the provider-independent layer and what tests assert on.
