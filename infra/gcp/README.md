# infra/gcp

Terraform for GCP (project `marginmaestro-demo`, region `us-central1`). Plan: `docs/gcp/GCP_ROADMAP.md`. The AWS Terraform in `infra/` stays untouched until Phase G9.

Prerequisites: gcloud configuration `marginmaestro` active, and Application Default Credentials set (`gcloud auth application-default login` + `set-quota-project marginmaestro-demo`).

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
- `outputs.tf` — project, region, service account emails.

CI (`terraform-gcp` job) runs `fmt -check` and `validate` on both roots with `-backend=false`, so it needs no GCP credentials.
