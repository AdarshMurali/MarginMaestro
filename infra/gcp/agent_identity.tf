# Agent Identity for the desk assistant (MM-131, ADR-0019).
#
# The agent runs as its own principal -- tied to its Agent Runtime resource,
# not a shared service account -- so every Gemini, Model Armor and MCP call in
# the audit log names the agent itself. The project has no organization, so
# the trust domain is project-level (agents.global.proj-<number>...).
#
# Cutover order (no outage): 1) apply this with mcp_legacy_sa_invoker = true
# (both identities may call the MCP services), 2) redeploy the agent with
# identity_type=AGENT_IDENTITY, 3) verify, 4) set mcp_legacy_sa_invoker = false
# and apply again, so only the agent principal can call the tools.

locals {
  desk_agent_principal = var.desk_agent_resource == "" ? "" : (
    "principal://agents.global.proj-${data.google_project.this.number}.system.id.goog/resources/aiplatform/${var.desk_agent_resource}"
  )

  # Google's recommended baseline for an agent identity (inference, sessions,
  # memory; quota; basic project access) plus telemetry and Model Armor,
  # which our guardrails call as the agent.
  desk_agent_roles = toset([
    "roles/aiplatform.expressUser",
    "roles/serviceusage.serviceUsageConsumer",
    "roles/browser",
    "roles/logging.logWriter",
    "roles/monitoring.metricWriter",
    "roles/cloudtrace.agent",
    "roles/modelarmor.user",
  ])
}

resource "google_project_iam_member" "desk_agent" {
  for_each = local.desk_agent_principal == "" ? toset([]) : local.desk_agent_roles

  project = var.project_id
  role    = each.value
  member  = local.desk_agent_principal
}

# The agent principal may call the read-only MCP services -- nothing else can
# once the cutover is complete.
resource "google_cloud_run_v2_service_iam_member" "mcp_desk_agent_invoker" {
  for_each = local.desk_agent_principal == "" ? {} : google_cloud_run_v2_service.mcp

  name     = each.value.name
  location = each.value.location
  role     = "roles/run.invoker"
  member   = local.desk_agent_principal
}

# MM-132: the on-demand evaluation job (GitHub Actions, as mm-ci-sa) queries
# the deployed agent and runs Vertex AI Gen AI evaluation.
resource "google_project_iam_member" "ci_evaluates_desk_agent" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.component["ci"].email}"
}

output "desk_agent_principal" {
  description = "The desk assistant's Agent Identity principal (empty until desk_agent_resource is set)"
  value       = local.desk_agent_principal
}
