variable "project_id" {
  description = "GCP project to deploy into"
  type        = string
  default     = "marginmaestro-demo"
}

variable "region" {
  description = "Default region. us-central1: full always-free tier, and Gemini / Agent Engine / Model Armor are all available there (ADR-0008)."
  type        = string
  default     = "us-central1"
}

variable "billing_account_id" {
  description = "Cloud Billing account linked to the project (currency INR)"
  type        = string
  default     = "01DE19-0D8CAC-54439D"
}

variable "killswitch_budget_inr" {
  description = "Cumulative trial spend (usage before credits, INR) at which billing is unlinked. 12600 INR ~ USD 150 (ADR-0017). Must be in the billing account's currency."
  type        = number
  default     = 12600
}

variable "killswitch_dry_run" {
  description = "When true the kill-switch only logs its decision. Set false only after a test notification has been verified end to end."
  type        = bool
  default     = false
}

variable "budget_alert_emails" {
  description = "Extra addresses for budget threshold emails (in addition to the billing account admins). Set in terraform.tfvars (gitignored) -- the repo is public, so no personal emails in code."
  type        = list(string)
  default     = []
}

variable "trial_start" {
  description = "Budget period start (free-trial start)"
  type        = object({ year = number, month = number, day = number })
  default     = { year = 2026, month = 9, day = 28 }
}

variable "trial_end" {
  description = "Budget period end (free-trial end, 90 days)"
  type        = object({ year = number, month = number, day = number })
  default     = { year = 2026, month = 12, day = 27 }
}

variable "environment" {
  description = "Deployment environment name, used in labels and the Secret Manager secret name (marginmaestro-<environment>)"
  type        = string
  default     = "prod"
}

variable "github_repository" {
  description = "GitHub repository trusted by Workload Identity Federation (label only -- access is matched on the numeric IDs below)"
  type        = string
  default     = "AdarshMurali/MarginMaestro"
}

variable "github_repository_id" {
  description = "Numeric GitHub repository ID (api.github.com/repos/<owner>/<repo> -> id). Matched instead of the name so a renamed or re-created repo can't inherit access."
  type        = string
  default     = "1310097546"
}

variable "github_repository_owner_id" {
  description = "Numeric GitHub ID of the repository owner (-> owner.id)"
  type        = string
  default     = "137914842"
}

variable "github_deploy_ref" {
  description = "Only workflow runs on this git ref may authenticate to GCP"
  type        = string
  default     = "refs/heads/main"
}

variable "demo_online" {
  description = "One on/off switch for the paid, always-running pieces (MM-120): true = Cloud SQL running (billed per hour) and the live-price schedule active; false = Cloud SQL stopped (storage only) and the schedule paused, so a stopped DB never piles up retries."
  type        = bool
  default     = false
}

variable "api_image" {
  description = "Initial API image for Cloud Run (MM-123). CD updates it on every merge to main; Terraform ignores later changes."
  type        = string
  default     = "docker.io/adarshmurali/marginmaestro:latest"
}

variable "frontend_origin" {
  description = "Browser origin allowed by the API's CORS policy (the Vercel frontend)."
  type        = string
  default     = "https://marginmaestro.vercel.app"
}
