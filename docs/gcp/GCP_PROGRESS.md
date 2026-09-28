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

- **Phase:** G0 (MM-87) in progress — MM-99 (Terraform foundation) and MM-98 (budget + kill-switch) done; next MM-100 (WIF + Artifact Registry).
- **GCP account:** `lavanyaasha71@gmail.com`, trial started **2026-09-28** ($300 / 90 days, ends ~2026-12-27). Month-2 cost review (G10) due **~2026-11-28**. Project `marginmaestro-demo` (no organization — pick "No organization" in the console project picker), billing account `01DE19-0D8CAC-54439D`, region `us-central1`. Local gcloud configuration: `marginmaestro`.
- **Decisions:** ADR-0008 … ADR-0017 accepted (`docs/gcp/adr/`).
- **Jira:** epics created 2026-09-28 — G0 MM-87 … G10 MM-97 (label `gcp`). Stories are created when each phase starts. G0 stories: MM-98 (G01 budget/kill-switch), MM-99 (G02 Terraform), MM-100 (G03 WIF + Artifact Registry), MM-101 (G04 Secret Manager), MM-102 (G05 adapter interfaces). Note: MM-100..102 were also *placeholder* keys in the old ROADMAP Phase 10 — those stories got real keys MM-81..85, so the real MM-100..102 are the G0 stories.
- **Live runtime:** still AWS EC2 + Azure SQL + Vercel (Phase 10) until Phase G9 cut-over.

## Phase status

| Phase | Epic | Scope | Status |
|---|---|---|---|
| G0 | MM-87 | Foundation, Terraform, WIF, Secret Manager, adapter interfaces, billing kill-switch | In progress (MM-99, MM-98 done) |
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
| 2026-09-28 | ₹0 (first real budget notification) | — | Kill-switch live at ₹12,600 (≈ $150) |

## Log

### 2026-09-28 — MM-98: Budget alerts + billing kill-switch
- **Done:** Trial budget `marginmaestro-demo trial kill-switch`: **₹4,200** (≈ $50), one cumulative period 2026-09-28 → 2026-12-27, counts usage **before credits** (`EXCLUDE_ALL_CREDITS`), email alerts at 2/20/50/80/100% (~₹84 / ₹840 / ₹2,100 / ₹3,360 / ₹4,200). Budget notifications → Pub/Sub `billing-alerts` → Cloud Run function `billing-killswitch` (Python 3.12, max 1 instance, internal ingress, retry on failure) → unlinks billing when cost ≥ budget. Deployed in **dry run** (`DRY_RUN=true`). Applied by the user.
- **Decisions:** Billing account currency is **INR**, so the $50 cap became ₹4,200 (budgets must use the account currency). Least privilege: `mm-killswitch-sa` gets **Project Billing Manager** on the project (exactly create/deleteBillingAssignment) instead of Google's documented Billing Account Administrator. Function code lives in `src/ops/billing_killswitch.py` and Terraform packages that same file as `main.py`, so the deployed code is what CI lints/tests. Dedicated `mm-build-sa` for builds (logWriter, artifactregistry.writer, project-level storage.objectViewer). Provider now sets `user_project_override`/`billing_project` (Budgets API rejects ADC without a quota project). New `gcp` extra in `pyproject.toml` (google-cloud-billing, functions-framework), installed in CI.
- **Changed:** `src/ops/` (new), `tests/unit/test_billing_killswitch.py` (16 tests), `infra/gcp/billing_killswitch.tf` (new), `infra/gcp/{providers,variables,service_accounts}.tf`, lock file (+ hashicorp/archive 2.8.1), `pyproject.toml`, `.github/workflows/ci.yml`, `.gitignore`.
- **Verified:** 545 passed, coverage 98% (kill-switch 100%); ruff/black/mypy clean; `terraform plan -detailed-exitcode` → no changes. End to end: a fake ₹5,000 notification published to `billing-alerts` logged `CRITICAL Budget reached; billing NOT unlinked (dry run)` (13:54 UTC); the first real Cloud Billing notification logged `INFO Spend within budget; no action` with cost ₹0 (14:12 UTC).
- **Cost impact:** none expected — Pub/Sub, Cloud Run functions, Cloud Build and Artifact Registry usage are within always-free quotas; source bucket objects auto-delete after 30 days.
- **Known issues / tech debt:** (0) Terraform now needs `infra/gcp/terraform.tfvars` (gitignored) with `budget_alert_emails` — without it the alert channel would be planned for removal. (1) First apply failed: Cloud Functions copies source into its own `gcf-v2-sources-<number>-us-central1` bucket, which the build account couldn't read — fixed with project-level objectViewer (the bucket doesn't exist before the first deploy, so a bucket-scoped grant isn't possible). (2) Fixed a `.gitignore` bug from MM-99: the appended `*.tfplan` had merged into the `.claude/settings.local.json` line, breaking both rules (no `.claude/` files were committed meanwhile). (4) PowerShell splits `-out=file.ext` flags; quote them (`"-out=mm98.tfplan"`).
- **Follow-up (same day, user decisions):** hard stop raised to **₹12,600 (≈ $150)** — half the credits, so alerts leave time to act before unlinking billing (which can delete resources); email alerts at ≈ $25 / $50 / $75 / $100 / $125 / $150 (₹2,100 … ₹12,600) also go to the user's monitoring address via a Cloud Monitoring email channel (address kept in gitignored `infra/gcp/terraform.tfvars` — public repo); kill-switch switched **live** (`killswitch_dry_run = false`). Verified: budget units 12600, 6 thresholds, 1 channel, function `ACTIVE` with `DRY_RUN=false`, `terraform plan` → no changes. The first apply hit a google-provider bug ("inconsistent final plan": budget referenced the new channel before it existed); a second apply completed it.
- **Next step:** MM-100 (Workload Identity Federation + Artifact Registry).

### 2026-09-28 — MM-99: Terraform foundation for GCP
- **Done:** New Terraform root `infra/gcp/` (AWS `infra/` untouched). `infra/gcp/bootstrap/` created the remote-state bucket `marginmaestro-demo-tfstate` (us-central1, versioned, public access prevention enforced, old versions pruned) — applied by the user. Foundation applied by the user from a saved plan: 9 APIs, 6 service accounts (`mm-api-sa`, `mm-agent-sa`, `mm-mcp-sa`, `mm-events-sa`, `mm-ci-sa`, `mm-killswitch-sa`), 12 telemetry role bindings (logWriter / cloudtrace.agent / metricWriter on the 4 runtime accounts). New CI job `terraform-gcp` (fmt -check + validate on both roots, no credentials needed).
- **Decisions:** `hashicorp/google ~> 8.4` (current release; the roadmap's earlier "7.x" was out of date). Region `us-central1`. APIs are enabled per story, only when first needed. Runtime accounts get only telemetry roles in G0; every other role is granted with the resource it applies to. Service account IDs use `mm-<name>-sa` (GCP requires 6–30 chars; `mm-ci` failed). Provider lock files include linux_amd64 + windows_amd64 hashes so CI and local agree.
- **Changed:** `infra/gcp/**` (new), `.github/workflows/ci.yml` (`terraform-gcp` job), `.gitignore` (`*.tfplan`), `docs/gcp/GCP_ROADMAP.md` (new "Open items" section: make ISDA *necessary* and give BigQuery a firm reporting requirement — user request, revisit after G8).
- **Verified:** `terraform plan -detailed-exitcode` after apply → no changes; `gcloud iam service-accounts list` shows all 6; bucket describe confirms location/versioning/public-access prevention.
- **Cost impact:** none — state bucket (KB-sized) is inside the 5 GB always-free tier; APIs and service accounts are free.
- **Known issues / tech debt:** project sits outside the `lavanyaasha71-org` organization (created via gcloud with no parent) — fine for the demo, no org policies apply.
- **Next step:** MM-98 — budget alerts + billing kill-switch.
- **Follow-up (same day, docs):** ADR-0010 and ADR-0014 amended to adopt Agent Platform's governance layer (Agent Identity, Agent Gateway with deny-by-default tool policies + Model Armor, Semantic Governance Policies) — new roadmap stories MM-G37 (G3) and MM-G56 (G5); pricing to be confirmed before enabling. ADR-0017 amended: kill-switch at **$50 cumulative for the trial**, budget counts usage before credits, alerts at $1/$10/$25/$40 (user decision; expected trial usage ~$25–60).

### 2026-09-28 — GCP track planning (no story key)
- **Done:** GCP migration plan agreed with the user. Wrote `docs/gcp/GCP_ROADMAP.md` (service catalog + Phases G0–G10) and ADR-0008 … ADR-0017. Moved all GCP docs into `docs/gcp/`; merged the earlier drafts (`GCP_MIGRATION.md`, `GCP_DEPLOYMENT_PLAN.md`) into the roadmap's *Background notes* and removed them. Marked old ROADMAP Phases 14/15 superseded and Phase 16 dropped; ADR-0004 and ADR-0006 superseded.
- **Decisions:** GCP is the primary platform; governance, guardrails and RLS are mandatory; Gemini on Vertex AI; LangGraph kept, hosted on Agent Engine; Cloud SQL Postgres + pgvector (user's choice) with RLS; Pub/Sub; BigQuery as the analytics/audit warehouse; WhatsApp for client notices (Slack kept internally); Gemini Live dropped. GCP-native services only during the trial; swap to free fallbacks at the month-2 review.
- **Changed:** docs only.
- **Cost impact:** none yet.
- **Known issues / tech debt:** none.
- **Next step:** Jira epics MM-87 … MM-97 created. Present the Phase G0 plan (specific tools/versions per story) for approval before any code.
