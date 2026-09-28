# ADR-0010: Host the LangGraph orchestrator on Vertex AI Agent Engine (Agent Platform)

- **Status:** Accepted
- **Date:** 2026-09-28
- **Amends:** ADR-0002 (LangGraph stays the orchestration framework)

## Context

Google's Agent Platform offers a managed runtime (Vertex AI **Agent Engine**), the Agent Development Kit (ADK), managed sessions/memory, and built-in tracing and evaluation. The question is whether to adopt it and how deeply.

## Decision

- **Keep LangGraph** (ADR-0002). Agent Engine supports LangGraph agents natively, so the existing state graph, `interrupt()` approval gates and tests carry over.
- **Deploy the orchestrator graph to Agent Engine** as the managed agent runtime. The FastAPI API on Cloud Run calls it for `/simulate`, approvals and resumes.
- **Checkpointing** moves from the custom SQL Server saver (`persistence/db/checkpoint_saver.py`) to LangGraph's official Postgres checkpointer on Cloud SQL (ADR-0011), so human-approval pauses survive restarts.
- **Evaluation:** use Vertex AI **Gen AI evaluation** for the golden scenario set (tool-call trajectory + grounding/citation checks), in CI on demand.
- **MCP servers** (market data, RAG retriever, Slack, WhatsApp, ServiceNow) run on Cloud Run and are called as tools by the agent.
- **Not adopted:** rewriting agents in ADK. It would cost a full rewrite for little gain; revisit only if a feature is ADK-only.

## Rationale

Managed hosting, sessions and tracing without giving up a working, tested orchestration layer.

## Consequences

- Agent Engine is billed by runtime vCPU/memory-hours — **the second-largest post-trial cost risk** after Cloud SQL. Fallback (ADR-0017): run the same graph in-process inside the Cloud Run API (`AGENT_RUNTIME=cloudrun`), which is exactly how it runs today.
- Agent-side code must not assume local filesystem or process state between requests.
