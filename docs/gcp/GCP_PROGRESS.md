# MarginMaestro — GCP Track Progress Log

Living handoff log for the GCP track (`docs/gcp/GCP_ROADMAP.md`). Stories from Phases G0–G10 log here, not in `docs/PROGRESS.md`. Same rules as the main log: update at the end of every story, as part of the Definition of Done.

At the end of each story, prepend an entry to **Log** using this template:

```markdown
### <YYYY-MM-DD> — <STORY KEY>: <title>
- **Done:** what was completed
- **Decisions:** key decisions (link ADR if any)
- **Changed:** files / modules / GCP resources touched
- **Cost impact:** new billable resources, and whether they're covered by the always-free tier after the trial
- **Known issues / tech debt:** anything deferred
- **Next step:** the exact next action
```

## Current state (snapshot)

- **Phase:** Planning done, nothing built yet. Next: Phase G0 (GCP foundation & cost guardrails).
- **GCP account:** free trial not opened yet ($300 / 90 days). Record the trial start date here once it is; the month-2 cost review (Phase G10) is due ~60 days after it.
- **Decisions:** ADR-0008 … ADR-0017 accepted (`docs/gcp/adr/`).
- **Jira:** epics created 2026-09-28 — G0 MM-87 … G10 MM-97 (label `gcp`). Stories are created when each phase starts.
- **Live runtime:** still AWS EC2 + Azure SQL + Vercel (Phase 10) until Phase G9 cut-over.

## Phase status

| Phase | Epic | Scope | Status |
|---|---|---|---|
| G0 | MM-87 | Foundation, Terraform, WIF, Secret Manager, adapter interfaces, billing kill-switch | Not started |
| G1 | MM-88 | Cloud SQL Postgres + pgvector + row-level security | Not started |
| G2 | MM-89 | Gemini on Vertex AI + RAG on pgvector | Not started |
| G3 | MM-90 | AI guardrails (Model Armor, SDP, in-code) | Not started |
| G4 | MM-91 | Pub/Sub, Cloud Tasks SLA timers, Cloud Scheduler | Not started |
| G5 | MM-92 | Agent Engine, Cloud Run deployment, observability | Not started |
| G6 | MM-93 | WhatsApp client notifications | Not started |
| G7 | MM-94 | BigQuery analytics & audit warehouse | Not started |
| G8 | MM-95 | Data governance (Dataplex, classification, lineage, audit, retention) | Not started |
| G9 | MM-96 | Cut-over & AWS/Azure decommission | Not started |
| G10 | MM-97 | Month-2 cost review & free-fallback swaps | Not started |

## Cost tracker

| Date | Credits used | Biggest spenders | Action |
|---|---|---|---|
| — | — | — | — |

## Log

### 2026-09-28 — GCP track planning (no story key)
- **Done:** GCP migration plan agreed with the user. Wrote `docs/gcp/GCP_ROADMAP.md` (service catalog + Phases G0–G10) and ADR-0008 … ADR-0017. Moved all GCP docs into `docs/gcp/`; merged the earlier drafts (`GCP_MIGRATION.md`, `GCP_DEPLOYMENT_PLAN.md`) into the roadmap's *Background notes* and removed them. Marked old ROADMAP Phases 14/15 superseded and Phase 16 dropped; ADR-0004 and ADR-0006 superseded.
- **Decisions:** GCP is the primary platform; governance, guardrails and RLS are mandatory; Gemini on Vertex AI; LangGraph kept, hosted on Agent Engine; Cloud SQL Postgres + pgvector (user's choice) with RLS; Pub/Sub; BigQuery as the analytics/audit warehouse; WhatsApp for client notices (Slack kept internally); Gemini Live dropped. GCP-native services only during the trial; swap to free fallbacks at the month-2 review.
- **Changed:** docs only.
- **Cost impact:** none yet.
- **Known issues / tech debt:** none.
- **Next step:** Jira epics MM-87 … MM-97 created. Present the Phase G0 plan (specific tools/versions per story) for approval before any code.
