# infra/gcp

Terraform for GCP (project `marginmaestro-demo`, region `us-central1`). Plan: `docs/gcp/GCP_ROADMAP.md`. The AWS Terraform in `infra/` stays untouched until Phase G9.

Prerequisites: gcloud configuration `marginmaestro` active, and Application Default Credentials set (`gcloud auth application-default login` + `set-quota-project marginmaestro-demo`).

Local, gitignored `terraform.tfvars` (the repo is public):

```hcl
budget_alert_emails = ["you@example.com"]
```

## First-time setup

```bash
# 1. Create the remote-state bucket (local state, run once)
terraform -chdir=infra/gcp/bootstrap init
terraform -chdir=infra/gcp/bootstrap apply

# 2. Everything else, with state in gs://marginmaestro-demo-tfstate
terraform -chdir=infra/gcp init
terraform -chdir=infra/gcp plan
terraform -chdir=infra/gcp apply
```

## Files

- `bootstrap/` — the state bucket only (versioned, public access blocked, old versions pruned). Its own state is local and gitignored.
- `providers.tf` — `hashicorp/google ~> 8.4`, default labels.
- `backend.tf` — GCS state backend (`marginmaestro-demo-tfstate`, prefix `infra/gcp`).
- `variables.tf` — `project_id`, `region`, `environment`.
- `apis.tf` — APIs the foundation needs. Later phases enable their own APIs in the story that first uses them.
- `service_accounts.tf` — one service account per component (`mm-api-sa`, `mm-agent-sa`, `mm-mcp-sa`, `mm-events-sa`, `mm-ci-sa`, `mm-killswitch-sa`, `mm-build-sa`, and `mm-invoker-sa` — the identity Pub/Sub push and Cloud Scheduler sign their OIDC tokens as, MM-121). Runtime accounts get only telemetry roles here; every other role is granted with the resource it applies to.
- `secrets.tf` — Secret Manager secret `marginmaestro-<environment>` (empty container; values added out-of-band with `gcloud secrets versions add`, never via Terraform) + `secretAccessor` on that one secret for the runtime accounts (MM-101).
- `cloud_sql.tf` — Cloud SQL `marginmaestro-pg` (Postgres 17, Enterprise `db-f1-micro`, zonal, 10 GB SSD, backups, deletion protection; public IP with no authorized networks), database `marginmaestro`, IAM database users + `cloudsql.client` / `cloudsql.instanceUser` for the runtime accounts (MM-108). Stop it when idle with `demo_online = false` (storage still billed; MM-120 — the same switch pauses the live-price schedule from G5). One-time data setup: `scripts/cloudsql_bootstrap.ps1` (proxy → migrations → seed → `mm_app` grants → RLS tests).
- `pubsub.tf` — Pub/Sub event topics (`market.prices`, `market.events`, `market.impact`, `margin.calls`) + `market.dead-letter`, per-topic publisher roles (MM-119); the Event Agent's ordered subscriptions `event-agent.market.prices` / `event-agent.market.events` with a dead-letter policy, pushing to `/internal/pubsub/push` on the API since MM-124 (MM-120); `orchestrator.market.impact` for the impact consumer (10-minute ack deadline, because runs call the LLM) and the Pub/Sub service agent's token-creator role on `mm-invoker-sa` (MM-121).
- `cloud_tasks.tf` — Cloud Tasks API and the `sla-checks` queue (retries with backoff for up to a day), `roles/cloudtasks.enqueuer` on it for `mm-api-sa` / `mm-agent-sa`, plus `serviceAccountUser` on `mm-invoker-sa` so their tasks carry its OIDC token (MM-122). Tasks target `INTERNAL_BASE_URL` (the Cloud Run URL, G5).
- `cloud_run.tf` — the API on Cloud Run, `marginmaestro-api` (MM-123): the Docker Hub image as `mm-api-sa`, min 0 / max 4 instances, CPU only during requests, 600 s timeout, Cloud SQL via the built-in connection with IAM database login (`DB_AUTH=iam`), GCP adapters on by env vars, public invoker (the app does its own auth). CD updates the image; Terraform ignores image changes. Output `api_url` is the deterministic URL (`marginmaestro-api-<project-number>.<region>.run.app`), stable across re-creation, and is also the OIDC audience (MM-124).
- `scheduler.tf` — Cloud Scheduler job `price-refresh`: every 5 minutes, Mon–Fri 09:00–15:55 New York time, POST `/internal/prices/refresh` with an OIDC token for `mm-invoker-sa`; paused whenever `demo_online = false` (MM-124). Also `eod-prices`: 16:30 New York Mon–Fri, POST `/internal/prices/eod` (official daily closes with a 7-day back-fill + FRED rates), same switch.
- `monitoring.tf` — one log-based metric `mm-incidents` (SLA breaches, guardrail blocks/outages, dead letters, 5xx; labelled by log `event`) and one email alert policy on it, sent to `budget_alert_emails` (MM-127). A single condition keeps alerting cost minimal.
- `vertex_ai.tf` — Vertex AI API + `aiplatform.user` for `mm-api-sa`, `mm-agent-sa`, `mm-mcp-sa` (MM-109).
- `documents.tf` — GCS bucket `marginmaestro-demo-documents` for the RAG corpus (versioned, private, old versions pruned) (MM-111). Upload: `python -m rag.gcs_documents data/documents`; ingest: `DOCUMENT_STORE=gcs python -m rag.ingest`.
- `outputs.tf` — project, region, service account emails, WIF provider, app secret id.

CI (`terraform-gcp` job) runs `fmt -check` and `validate` on both roots with `-backend=false`, so it needs no GCP credentials.
- `wif.tf` — Workload Identity Federation for GitHub Actions (MM-100): pool `github`, provider `github-actions` trusting only this repo (numeric repo + owner IDs) on `refs/heads/main`, and `workloadIdentityUser` on `mm-ci-sa` for that repo only. `mm-ci-sa` has no project roles yet (deploy roles come in G5, MM-G57).
- `billing_killswitch.tf` — trial budget (₹12,600 ≈ $150, usage before credits, alerts at ≈ $25/$50/$75/$100/$125), Pub/Sub `billing-alerts`, and the live `billing-killswitch` function (code: `src/ops/billing_killswitch.py`) that unlinks billing at 100%.

## GitHub Actions login (MM-100)

After applying `wif.tf`, copy two outputs into GitHub → repo **Settings → Secrets and variables → Actions → Variables** (plain variables, not secrets — both are public identifiers):

```bash
terraform -chdir=infra/gcp output -raw github_wif_provider        # -> GCP_WIF_PROVIDER
terraform -chdir=infra/gcp output -raw github_ci_service_account  # -> GCP_CI_SERVICE_ACCOUNT
```

The `deploy-gcp` CI job (push to `main` only; it replaced the `gcp-auth` proof job in MM-126) logs in this way, deploys the commit's image to Cloud Run and smoke-tests it. `mm-ci-sa` holds `roles/run.developer` on the `marginmaestro-api` service only, plus `roles/iam.serviceAccountUser` on `mm-api-sa` only (`cloud_run.tf`). To revoke GitHub's access, delete the provider or the IAM binding — there is no key to rotate.
