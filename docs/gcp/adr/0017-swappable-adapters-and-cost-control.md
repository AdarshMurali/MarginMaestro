# ADR-0017: Swappable adapters and post-trial cost control

- **Status:** Accepted (amended 2026-09-28: kill-switch at $150 / INR 12,600, live)
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
- **Budget: $150 (INR 12,600 — the billing account is in INR) for the whole trial**, not per month. Custom budget period 2026-09-28 → 2026-12-27, so the amount is cumulative. Expected trial usage is roughly $25–60 in total (Cloud SQL ~$9–10/month is the main line item). The hard stop sits at half the $300 credits so that early alerts leave time to act before anything is shut down (user decision: unlinking billing can delete resources).
- **Budget counts usage before credits** (`credit_types_treatment = EXCLUDE_ALL_CREDITS`). Otherwise credits would cover everything, spend would read $0 and the kill-switch would never fire.
- **Alerts** at ≈ $25 / $50 / $75 / $100 / $125 / $150 (email to the billing admins and to the monitoring address set in `terraform.tfvars`).
- **Billing kill-switch at $150 (live):** budget notification → Pub/Sub → Cloud Run function that detaches the billing account from the project when actual spend reaches the budget. Verified in dry-run mode with a fake notification before going live. Detaching billing stops all paid services immediately — the demo goes offline rather than overspending.
- Cloud Run `min-instances=0`; no load balancer or static IP (use the default `run.app` HTTPS URL); partitioned BigQuery tables.

**3. Month-2 review (~2026-11-28).** Review billing, then swap each post-trial cost item to its fallback before the trial ends. Known post-trial cost items, in order of risk:

| Service | Post-trial risk | Planned action |
|---|---|---|
| Cloud SQL | High (no free tier) | → Neon / Supabase free Postgres |
| Agent Engine | High (runtime hours) | → in-process on Cloud Run |
| Vertex AI Gemini | Medium (per token) | → AI Studio free tier or OpenAI |
| Dataplex scans | Medium | → governance-as-code |
| Model Armor / SDP | Low–Medium (small free quotas) | → in-code + Presidio if quota exceeded |
| Cloud Run, Pub/Sub, BigQuery, Secret Manager, Cloud Tasks/Scheduler, Logging/Trace | Low (always-free quotas) | keep |

**Container images stay on Docker Hub (amended 2026-09-29, MM-100, user decision).** The original plan moved images to Artifact Registry with Docker Hub as a mirror. Reversed: anything stored in the GCP project is stopped and eventually deleted if the trial ends or the kill-switch unlinks billing, while Docker Hub is independent of GCP. Cloud Run deploys public Docker Hub images directly and keeps its own copy per revision, so a running service doesn't depend on Docker Hub being up. One image (`adarshmurali/marginmaestro:<sha>`) serves every environment; only config differs. If the repo ever goes private, add an Artifact Registry *remote* repository (a pull-through cache with the Docker Hub token in Secret Manager) rather than moving the images.

## Consequences

- Slightly more code up front (an interface per dependency) in exchange for one-flag swaps later.
- After the trial the account must be upgraded to paid to keep using always-free quotas; the kill-switch caps any overspend.
