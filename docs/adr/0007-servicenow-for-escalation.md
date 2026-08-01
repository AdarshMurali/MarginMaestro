# ADR-0007: Use ServiceNow (not Jira) for margin-call escalation incidents

- **Status:** Accepted
- **Date:** 2026-08-01

## Context

`CLAUDE.md`'s original tech stack listed Jira as this project's ticketing/escalation tool, with a note that a swap to ServiceNow for the escalation path specifically was "planned... needs an ADR before it actually changes" (`docs/ROADMAP.md`'s 2026-07-25 Phase 6 note; `docs/AGENTS.md`'s SLA & Escalation section carries the same note). Jira is already in use elsewhere in this project as the dev-story tracker (every `MM-#` ticket, created and updated by the agent per session).

MM-43 (Phase 6) needs to open a real ticket when a margin call's SLA is breached (`docs/AGENTS.md`: "follow the escalation-procedures document, retrieved via RAG, and open a ServiceNow incident with full context"). Using Jira for this would conflate two very different things under one tool: an engineering backlog (`MM-#` stories) and a business/operational escalation (a client margin call going unanswered past its SLA). Jira is purpose-built for the former; ServiceNow's Incident Management is purpose-built for the latter, and is the tool a real bank's ops team would actually use for this kind of alert.

The user holds a free ServiceNow Personal Developer Instance (PDI), obtained from developer.servicenow.com, making this a zero-cost choice consistent with the project's "free + synthetic data" constraint.

## Decision

Margin-call SLA-breach escalations (MM-43) open an incident in **ServiceNow**, via its REST Table API (`POST /api/now/table/incident`) against the user's free PDI, authenticated with HTTP Basic Auth (instance URL + username + password — the same auth shape already used for this project's own DB credentials, no OAuth flow needed for a dev instance).

**Scope is narrow and explicit:** this swap applies *only* to the SLA-escalation incident-opening path. Jira remains completely unaffected as this project's own dev-story tracker — every `MM-#` ticket continues to live in Jira, created/updated the same way as before. Nothing about this decision touches Jira's role in the project's own delivery workflow.

## Rationale

- **Semantic fit:** ServiceNow Incident Management models "something needs urgent operational attention" (an SLA breach, an outage) far more naturally than a software issue tracker does. Using Jira for both engineering stories and business escalations would make both harder to reason about (noisy backlog, wrong workflow states, wrong audience).
- **Zero cost:** the user already has a free ServiceNow PDI — no new spend, consistent with `CLAUDE.md`'s "free + synthetic" constraint.
- **Matches what a real ops team would use:** ServiceNow is a standard ITSM tool for exactly this kind of incident in real financial-services operations, which keeps this demo's design "directionally correct" (per the same spirit as `ADR-0005`'s calc-vs-LLM boundary — model the real workflow shape, not a shortcut).
- **Already anticipated:** `docs/ROADMAP.md` and `docs/AGENTS.md` both named ServiceNow for this path months before this ADR — this formalizes an already-agreed direction, not a new proposal.

## Alternatives

- **Keep Jira for escalation too:** rejected — conflates dev-story tracking with business escalation as described above; would also mean inventing an artificial issue type/workflow in Jira to distinguish "MM-# engineering story" from "client SLA breach," adding complexity Jira isn't designed for.
- **PagerDuty or another dedicated incident-management tool:** rejected — no free instance as readily available as ServiceNow's PDI program, and ServiceNow was already the named choice in this project's own docs before this ADR was written; switching to a third tool would mean re-deciding a question that's already settled.

## Consequences

- New `Settings` fields: `servicenow_instance_url`, `servicenow_username`, `servicenow_password` (mirrors the existing `slack_bot_token`/`slack_channel_id` pattern from MM-9/MM-41 — env-var-sourced locally, AWS Parameter Store when deployed).
- New `src/mcp_servers/servicenow.py` MCP tool wrapping incident creation, following the same thin-wrapper pattern as `rag_retriever.py` (MM-25) and `slack_notifier.py` (MM-41).
- `CLAUDE.md`'s tech stack line is updated to state the ServiceNow swap as decided (this ADR), not merely "planned."
- MM-43's real-account verification (per its exit criteria) requires the user's actual PDI credentials, supplied via their local `.env` — never pasted into chat or committed.
