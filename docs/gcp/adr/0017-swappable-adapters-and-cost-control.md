# ADR-0017: Swappable adapters and post-trial cost control

- **Status:** Accepted
- **Date:** 2026-09-28

## Context

The GCP plan uses GCP-native services while the $300 / 90-day trial credits last. After the trial, some services bill with no free tier. The app is a demo: it must cost as close to $0 as possible afterwards, and any single piece must be swappable without touching the rest.

## Decision

**1. Ports and adapters.** Every external dependency sits behind a Python interface (`typing.Protocol`) with a GCP adapter and at least one free fallback, selected by an env flag in `Settings`:

| Interface | Env flag | GCP adapter (trial) | Free fallback (post-trial) |
|---|---|---|---|
| `LLMClient` / `Embedder` | `LLM_PROVIDER` | Vertex AI Gemini | AI Studio free tier / OpenAI |
| Agent runtime | `AGENT_RUNTIME` | Agent Engine | in-process on Cloud Run |
| `Repository` + `VectorStore` | `DATABASE_URL` | Cloud SQL Postgres + pgvector | Neon / Supabase free Postgres + pgvector |
| `EventBus` | `EVENT_BUS` | Pub/Sub | Redpanda / Kafka |
| `Warehouse` | `WAREHOUSE` | BigQuery | (stays BigQuery — free tier) |
| `Guardrail` | `GUARDRAIL_PROVIDER` | Model Armor + SDP | in-code checks + Presidio |
| `Notifier` | `CLIENT_NOTIFIER` | WhatsApp Cloud API | Slack |
| Secrets | `SECRETS_SOURCE` | Secret Manager | env vars |
| Tracing | `OTEL_EXPORTER` | Cloud Trace | Jaeger |

**Contract tests** run the same test suite against every adapter of an interface, so a swap is a config change that is already proven to work. **Terraform** has one module per provider, each behind an `enable_*` toggle.

**2. Cost guardrails from day one.**
- Budget alert at $1 (and 50% / 90% of credits).
- **Billing kill-switch:** budget notification → Pub/Sub → Cloud Run function that detaches the billing account from the project if actual spend exceeds the threshold.
- Cloud Run `min-instances=0`; no load balancer or static IP (use the default `run.app` HTTPS URL); partitioned BigQuery tables.

**3. Month-2 review (~2026-11-28).** Review billing, then swap each post-trial cost item to its fallback before the trial ends. Known post-trial cost items, in order of risk:

| Service | Post-trial risk | Planned action |
|---|---|---|
| Cloud SQL | High (no free tier) | → Neon / Supabase free Postgres |
| Agent Engine | High (runtime hours) | → in-process on Cloud Run |
| Vertex AI Gemini | Medium (per token) | → AI Studio free tier or OpenAI |
| Dataplex scans | Medium | → governance-as-code |
| Model Armor / SDP | Low–Medium (small free quotas) | → in-code + Presidio if quota exceeded |
| Cloud Run, Pub/Sub, BigQuery, Secret Manager, Cloud Tasks/Scheduler, Logging/Trace, Artifact Registry | Low (always-free quotas) | keep |

## Consequences

- Slightly more code up front (an interface per dependency) in exchange for one-flag swaps later.
- After the trial the account must be upgraded to paid to keep using always-free quotas; the kill-switch caps any overspend.
