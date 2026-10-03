# Alerting (MM-127, MM-G54): one log-based metric that counts operational
# incidents in the API's logs, and one email alert on it. A single metric
# with an `event` label (rather than one metric + policy per incident type)
# keeps it to one alert condition -- Cloud Monitoring bills alerting per
# condition -- while the alert still says which kind fired.
#
# Counted:
#   sla_breached              a client missed a margin-call SLA (escalated)
#   guardrail_verdict=blocked an LLM prompt/response was blocked
#   guardrail_unavailable     a guardrail couldn't screen (calls fail closed)
#   event_agent_dead_lettered an event was dead-lettered after retries
#   (no event)                any 5xx response from the API
#
# Emails go to var.budget_alert_emails (gitignored tfvars), like the budget.

resource "google_logging_metric" "incidents" {
  name        = "mm-incidents"
  description = "MarginMaestro API operational incidents, labelled by log event"
  # replace(): Windows checkouts add \r to heredocs, which would show as a diff.
  filter = replace(<<-EOT
    resource.type="cloud_run_revision"
    resource.labels.service_name="${google_cloud_run_v2_service.api.name}"
    (
      jsonPayload.event="sla_breached"
      OR (jsonPayload.event="guardrail_verdict" AND jsonPayload.outcome="blocked")
      OR jsonPayload.event="guardrail_unavailable"
      OR jsonPayload.event="event_agent_dead_lettered"
      OR httpRequest.status>=500
    )
  EOT
  , "\r", "")

  metric_descriptor {
    metric_kind  = "DELTA"
    value_type   = "INT64"
    unit         = "1"
    display_name = "MarginMaestro incidents"

    labels {
      key         = "event"
      value_type  = "STRING"
      description = "Log event name (empty for 5xx request logs)"
    }
  }

  label_extractors = {
    event = "EXTRACT(jsonPayload.event)"
  }
}

resource "google_monitoring_notification_channel" "email" {
  for_each = toset(var.budget_alert_emails)

  display_name = "MarginMaestro alerts (${each.value})"
  type         = "email"
  labels = {
    email_address = each.value
  }
}

resource "google_monitoring_alert_policy" "incidents" {
  display_name = "MarginMaestro: operational incident"
  combiner     = "OR"

  conditions {
    display_name = "Incident logged (SLA breach, guardrail block/outage, dead letter, 5xx)"

    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.incidents.name}\" AND resource.type=\"cloud_run_revision\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"

      aggregations {
        alignment_period     = "300s"
        per_series_aligner   = "ALIGN_SUM"
        cross_series_reducer = "REDUCE_SUM"
        group_by_fields      = ["metric.label.event"]
      }

      trigger {
        count = 1
      }
    }
  }

  alert_strategy {
    auto_close = "1800s"
  }

  documentation {
    mime_type = "text/markdown"
    content = replace(<<-EOT
      An operational incident was logged by the MarginMaestro API. The `event`
      label says which: `sla_breached` (a margin call was escalated to
      ServiceNow), `guardrail_verdict` (an LLM call was blocked),
      `guardrail_unavailable` (screening failed, calls fail closed),
      `event_agent_dead_lettered` (an event gave up after retries), or empty
      (a 5xx response). Logs: Cloud Logging, service marginmaestro-api; each
      line links to its trace in Cloud Trace.
    EOT
    , "\r", "")
  }

  notification_channels = [for channel in google_monitoring_notification_channel.email : channel.id]
}

# Cloud Trace stores spans in an Observability bucket (`_Trace`) on newer
# projects; without this API the bucket doesn't exist and the trace read API
# returns "_Trace bucket not found" (found verifying MM-127). Free to enable.
resource "google_project_service" "observability" {
  service            = "observability.googleapis.com"
  disable_on_destroy = false
}
