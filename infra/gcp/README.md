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
- `service_accounts.tf` — one service account per component (`mm-api-sa`, `mm-agent-sa`, `mm-mcp-sa`, `mm-events-sa`, `mm-ci-sa`, `mm-killswitch-sa`). Runtime accounts get only telemetry roles here; every other role is granted with the resource it applies to.
- `secrets.tf` — Secret Manager secret `marginmaestro-<environment>` (empty container; values added out-of-band with `gcloud secrets versions add`, never via Terraform) + `secretAccessor` on that one secret for the runtime accounts (MM-101).
- `cloud_sql.tf` — Cloud SQL `marginmaestro-pg` (Postgres 17, Enterprise `db-f1-micro`, zonal, 10 GB SSD, backups, deletion protection; public IP with no authorized networks), database `marginmaestro`, IAM database users + `cloudsql.client` / `cloudsql.instanceUser` for the runtime accounts (MM-108). Stop it when idle with `cloudsql_activation_policy = "NEVER"` (storage still billed). One-time data setup: `scripts/cloudsql_bootstrap.ps1` (proxy → migrations → seed → `mm_app` grants → RLS tests).
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

The `gcp-auth` CI job (push to `main` only) then mints a short-lived token for `mm-ci-sa`; it goes green only if the provider, condition and IAM binding are all correct. To revoke GitHub's access, delete the provider or the IAM binding — there is no key to rotate.
