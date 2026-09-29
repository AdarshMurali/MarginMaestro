# ADR-0008: Move MarginMaestro to GCP as the primary platform

- **Status:** Accepted
- **Date:** 2026-09-28
- **Supersedes:** Phase 10's AWS EC2 + Elastic IP runtime (`infra/compute.tf`), AWS Secrets Manager (MM-102), and the "additive portability only" framing of the old Phase 14 in `docs/ROADMAP.md`

## Context

MarginMaestro runs on a hybrid stack today: API + Chroma on one AWS EC2 box, Azure SQL for relational data, Redpanda locally, Vercel for the frontend, OpenAI for the LLM. The user is opening a new GCP account with the **$300 / 90-day free trial** and wants GCP to become the primary platform — not a side target — with governance, guardrails and row-level security treated as **mandatory**, not optional.

Cost stance agreed with the user: during the trial, use **GCP-native services only** and let the credits cover anything billable. At roughly the **2-month mark**, review billing and swap any piece that would cost money after the trial to a free fallback (see ADR-0017). The app is a demo; it will be stopped rather than paid for.

## Decision

GCP becomes the primary runtime. Service-by-service choices are recorded in their own ADRs:

| Concern | GCP service | ADR |
|---|---|---|
| LLM + embeddings | Gemini on Vertex AI | 0009 |
| Agent runtime | Vertex AI Agent Engine (Agent Platform), LangGraph kept | 0010 |
| Relational DB, vectors, RLS | Cloud SQL for PostgreSQL + pgvector | 0011 |
| Event bus | Pub/Sub | 0012 |
| Analytics / audit warehouse | BigQuery | 0013 |
| AI guardrails | Model Armor + Sensitive Data Protection + in-code checks | 0014 |
| Data governance | Dataplex Universal Catalog, policy tags, Cloud Audit Logs | 0015 |
| Client notifications | WhatsApp Business Cloud API (Slack kept for internal ops) | 0016 |
| Swappability + cost control | Ports/adapters, budget kill-switch, month-2 review | 0017 |

Platform services shared by all of the above:

- **Cloud Run** — API, MCP servers, Pub/Sub push consumers, frontend (min-instances = 0).
- **Docker Hub** stays the container registry (amended 2026-09-29, see ADR-0017) — Artifact Registry is not used for app images.
- **Secret Manager** — replaces AWS Secrets Manager; same single-JSON-secret shape (`marginmaestro-<app_env>`).
- **Cloud Tasks** — schedules the SLA-deadline check at the exact deadline, replacing today's re-pause polling in the orchestrator's SLA node.
- **Cloud Scheduler** — periodic jobs (price refresh, daily BigQuery rollups).
- **Cloud Storage** — RAG source documents (replaces the S3 bucket).
- **Cloud Logging / Cloud Trace / Cloud Monitoring** — OTel traces and structured JSON logs go here; replaces self-hosted Jaeger/Prometheus/Grafana in the deployed env (they stay for local dev).
- **IAM + Workload Identity Federation** — GitHub Actions deploys without long-lived keys (this repo on `main` only, MM-100); one least-privilege service account per service.
- **Cloud Billing budgets** — alert + automatic billing kill-switch (ADR-0017).
- **Terraform** — all of the above, in `infra/gcp/`.

## Rationale

- Serverless, scale-to-zero services remove the always-on EC2 box and its start/stop schedule.
- Moving the DB into GCP removes the cross-cloud Azure SQL firewall/static-IP problem that drove the EC2 + EIP decision.
- GCP's governance tooling (Dataplex, policy tags, BigQuery row access policies, Model Armor) directly covers the now-mandatory governance and guardrail requirements.

## Consequences

- AWS resources are decommissioned only after the GCP deployment passes the full E2E demo (`make demo` against the Cloud Run URL).
- `CLAUDE.md`'s tech stack section must be updated as each ADR lands.
- Local dev keeps Docker Compose; GCP emulators (Pub/Sub) and a local Postgres + pgvector container replace Redpanda/Chroma/SQL Server locally.
- Golden rules are unchanged: LLM never does math (ADR-0005), human approval before any client-facing call.
