# ADR-0002: Use LangGraph for agent orchestration

- **Status:** Accepted
- **Date:** 2026-07-23

## Context

The margin-call lifecycle is a multi-step workflow with real branching (breach vs no-breach, approve vs reject, SLA met vs escalate) and a required human-in-the-loop pause. We need orchestration that is deterministic, inspectable, testable, and auditable — not a free-running agent loop.

Options considered: a hand-rolled orchestration loop; CrewAI; AutoGen; LangGraph.

## Decision

Use **LangGraph**. The workflow is modelled as an explicit **state graph**: nodes are agents or deterministic steps, edges encode control flow. A single typed run-state threads through the graph.

## Rationale

- **Explicit control flow** matches a regulated financial workflow better than emergent multi-agent chat (CrewAI/AutoGen lean conversational).
- **Inspectable & testable** — we can assert the graph takes the correct branch given an input, with mocked LLM/tools.
- **Human-in-the-loop** pause/resume is first-class.
- **Demoable** — the graph can be visualized, which doubles as documentation and a resume artifact.

## Consequences

- Orchestration logic lives in code, not model improvisation → predictable and auditable.
- Slightly more upfront wiring than a conversational framework, but far better control.
- Swapping frameworks later would require a new ADR.
