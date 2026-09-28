# One service account per component, so each gets only the roles it needs.
# G0 grants only telemetry roles (logs, traces, metrics); every other role is
# granted in the story that creates the resource it applies to, scoped to that
# resource where GCP allows it (e.g. secretAccessor on one secret in MM-101).
locals {
  service_accounts = {
    api        = "MarginMaestro API (Cloud Run)"
    agent      = "MarginMaestro orchestrator (Agent Engine)"
    mcp        = "MarginMaestro MCP servers (Cloud Run)"
    events     = "MarginMaestro event consumers (Pub/Sub push)"
    ci         = "MarginMaestro CI/CD (GitHub Actions via WIF)"
    killswitch = "MarginMaestro billing kill-switch"
  }

  runtime_accounts = ["api", "agent", "mcp", "events"]

  telemetry_roles = [
    "roles/logging.logWriter",
    "roles/cloudtrace.agent",
    "roles/monitoring.metricWriter",
  ]

  runtime_telemetry_bindings = {
    for pair in setproduct(local.runtime_accounts, local.telemetry_roles) :
    "${pair[0]}:${pair[1]}" => { account = pair[0], role = pair[1] }
  }
}

resource "google_service_account" "component" {
  for_each = local.service_accounts

  account_id   = "mm-${each.key}-sa"
  display_name = each.value

  depends_on = [google_project_service.foundation]
}

resource "google_project_iam_member" "runtime_telemetry" {
  for_each = local.runtime_telemetry_bindings

  project = var.project_id
  role    = each.value.role
  member  = "serviceAccount:${google_service_account.component[each.value.account].email}"
}
