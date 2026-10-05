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

variable "desk_agent_resource" {
  description = "The desk assistant on Agent Runtime (projects/<p>/locations/<l>/reasoningEngines/<id>), printed by `python -m desk_assistant.deploy` (MM-129). Empty keeps chat off."
  type        = string
  default     = ""
}

variable "mcp_legacy_sa_invoker" {
  description = "mm-agent-sa may invoke the MCP services. Keep true while the agent runs as mm-agent-sa (MM-131: Agent Identity is off); set false only after an Agent Identity cutover."
  type        = bool
  default     = true
}

# --- G6: WhatsApp client notices, Slack for internal traffic (ADR-0016) ------

variable "client_notifier" {
  description = "Who receives client-facing margin-call notices (MM-118): slack (until the WhatsApp secrets and the Meta webhook are set up) or whatsapp."
  type        = string
  default     = "slack"

  validation {
    condition     = contains(["slack", "whatsapp"], var.client_notifier)
    error_message = "client_notifier must be \"slack\" or \"whatsapp\"."
  }
}

variable "internal_notifier" {
  description = "Internal firm traffic on Slack (MM-134): approval requests, client acknowledgements, delivery failures, escalations, the daily run summary. none turns it off."
  type        = string
  default     = "slack"

  validation {
    condition     = contains(["none", "slack"], var.internal_notifier)
    error_message = "internal_notifier must be \"none\" or \"slack\"."
  }
}

variable "whatsapp_phone_number_id" {
  description = "WhatsApp Cloud API sender: the Meta test number's phone_number_id (not a secret)."
  type        = string
  default     = "1382503808268641"
}

variable "whatsapp_template_name" {
  description = "Approved utility template for business-initiated notices (empty = free-form text, 24-hour window only)."
  type        = string
  default     = "margin_call_notice"
}

variable "whatsapp_template_language" {
  description = "Language code the template was approved in."
  type        = string
  default     = "en_US"
}

variable "whatsapp_graph_version" {
  description = "Meta Graph API version for /messages."
  type        = string
  default     = "v23.0"
}

# --- G8: data governance (ADR-0015) -------------------------------------------

variable "lineage_exporter" {
  description = "Per-margin-call lineage (MM-136): datalineage (OpenLineage events to the Data Lineage API, best effort) or none."
  type        = string
  default     = "datalineage"

  validation {
    condition     = contains(["none", "datalineage"], var.lineage_exporter)
    error_message = "lineage_exporter must be \"none\" or \"datalineage\"."
  }
}

variable "documents_retention_days" {
  description = "GCS retention policy on the documents bucket (MM-137): an object can't be deleted or replaced until it is this old. Not locked -- a locked policy can never be shortened or removed."
  type        = number
  default     = 30
}

variable "sdp_scan_period_days" {
  description = "How often the Sensitive Data Protection inspection job re-scans the documents bucket (MM-137). 1-60 days."
  type        = number
  default     = 30

  validation {
    condition     = var.sdp_scan_period_days >= 1 && var.sdp_scan_period_days <= 60
    error_message = "sdp_scan_period_days must be between 1 and 60."
  }
}

variable "desk_agent_identity" {
  description = "Grant the desk assistant's Agent Identity principal its roles (MM-131). Off: Agent Identity's mTLS-bound tokens can't reach Model Armor's regional endpoint, so the agent runs as mm-agent-sa."
  type        = bool
  default     = false
}
