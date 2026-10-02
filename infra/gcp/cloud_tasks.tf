# SLA timers (MM-122, ADR-0012): one Cloud Tasks task per margin call,
# scheduled for its SLA deadline, calling POST /internal/sla/{thread}/check
# with an OIDC token for mm-invoker-sa. Free tier: 1M operations/month --
# the demo creates a handful of tasks a day.
#
# The task target URL is the API's Cloud Run URL (INTERNAL_BASE_URL), set in
# G5; until then SLA_SCHEDULER stays "none" and nothing enqueues.

resource "google_project_service" "cloudtasks" {
  service            = "cloudtasks.googleapis.com"
  disable_on_destroy = false
}

resource "google_cloud_tasks_queue" "sla_checks" {
  name     = "sla-checks"
  location = var.region

  rate_limits {
    max_dispatches_per_second = 5
    max_concurrent_dispatches = 5
  }

  # 503 = "deadline not reached yet" or the API is down: back off and retry,
  # for up to a day.
  retry_config {
    max_attempts       = 20
    min_backoff        = "30s"
    max_backoff        = "600s"
    max_doublings      = 4
    max_retry_duration = "86400s"
  }

  depends_on = [google_project_service.cloudtasks]
}

# Who schedules: the orchestrator, which runs in the API today (api) and on
# Agent Engine from G5 (agent). Enqueue on this queue only, and "act as" the
# invoker so the tasks can carry its OIDC token.
resource "google_cloud_tasks_queue_iam_member" "enqueuers" {
  for_each = toset(["api", "agent"])

  name     = google_cloud_tasks_queue.sla_checks.name
  location = google_cloud_tasks_queue.sla_checks.location
  role     = "roles/cloudtasks.enqueuer"
  member   = "serviceAccount:${google_service_account.component[each.value].email}"
}

resource "google_service_account_iam_member" "enqueuers_act_as_invoker" {
  for_each = toset(["api", "agent"])

  service_account_id = google_service_account.component["invoker"].name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.component[each.value].email}"
}
