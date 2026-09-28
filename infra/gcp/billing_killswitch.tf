# Trial budget + billing kill-switch (MM-98, ADR-0017).
#
# Budget (usage before credits, whole trial) --notifies--> Pub/Sub topic
#   --Eventarc--> Cloud Run function (src/ops/billing_killswitch.py)
#   --> unlinks billing from the project once cost >= budget amount.
#
# Budget emails go to the billing account's admins (default IAM recipients)
# plus var.budget_alert_emails via Cloud Monitoring email channels.

locals {
  killswitch_apis = [
    "billingbudgets.googleapis.com",
    "cloudbilling.googleapis.com",
    "pubsub.googleapis.com",
    "cloudfunctions.googleapis.com",
    "run.googleapis.com",
    "eventarc.googleapis.com",
    "cloudbuild.googleapis.com",
    "artifactregistry.googleapis.com",
  ]

  killswitch_sa = google_service_account.component["killswitch"]
  build_sa      = google_service_account.component["build"]
}

resource "google_project_service" "killswitch" {
  for_each = toset(local.killswitch_apis)

  service            = each.value
  disable_on_destroy = false
}

data "google_project" "this" {}

# --- Notifications ----------------------------------------------------------

resource "google_pubsub_topic" "billing_alerts" {
  name = "billing-alerts"

  depends_on = [google_project_service.killswitch]
}

resource "google_billing_budget" "trial" {
  billing_account = var.billing_account_id
  display_name    = "${var.project_id} trial kill-switch"

  budget_filter {
    projects = ["projects/${data.google_project.this.number}"]

    # Count usage before credits; otherwise trial credits zero out the spend
    # and the kill-switch could never trip.
    credit_types_treatment = "EXCLUDE_ALL_CREDITS"

    # One cumulative period for the whole trial instead of a monthly reset.
    custom_period {
      start_date {
        year  = var.trial_start.year
        month = var.trial_start.month
        day   = var.trial_start.day
      }
      end_date {
        year  = var.trial_end.year
        month = var.trial_end.month
        day   = var.trial_end.day
      }
    }
  }

  amount {
    specified_amount {
      currency_code = "INR"
      units         = tostring(var.killswitch_budget_inr)
    }
  }

  # Email alerts at ~USD 25 / 50 / 75 / 100 / 125 / 150 of a INR 12,600 budget
  # (INR 2,100 / 4,200 / 6,300 / 8,400 / 10,500 / 12,600). The kill-switch
  # acts only at 100% (USD 150).
  dynamic "threshold_rules" {
    for_each = [0.1667, 0.3333, 0.5, 0.6667, 0.8333, 1.0]
    content {
      threshold_percent = threshold_rules.value
      spend_basis       = "CURRENT_SPEND"
    }
  }

  all_updates_rule {
    pubsub_topic                     = google_pubsub_topic.billing_alerts.id
    schema_version                   = "1.0"
    disable_default_iam_recipients   = false
    enable_project_level_recipients  = false
    monitoring_notification_channels = [for c in google_monitoring_notification_channel.budget_email : c.id]
  }

  depends_on = [google_project_service.killswitch]
}

resource "google_monitoring_notification_channel" "budget_email" {
  for_each = toset(var.budget_alert_emails)

  display_name = "Budget alerts: ${each.value}"
  type         = "email"
  labels = {
    email_address = each.value
  }
}

# --- Function source (the same file CI lints and tests) --------------------

resource "google_storage_bucket" "function_source" {
  name     = "${var.project_id}-function-source"
  location = upper(var.region)

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  lifecycle_rule {
    condition {
      age = 30
    }
    action {
      type = "Delete"
    }
  }
}

data "archive_file" "killswitch" {
  type        = "zip"
  output_path = "${path.module}/.build/billing_killswitch.zip"

  source {
    filename = "main.py"
    content  = file("${path.module}/../../src/ops/billing_killswitch.py")
  }

  source {
    filename = "requirements.txt"
    content  = "functions-framework\ngoogle-cloud-billing\npydantic\n"
  }
}

resource "google_storage_bucket_object" "killswitch_source" {
  # Content hash in the name: a code change uploads a new object, which
  # makes Terraform redeploy the function.
  name   = "billing-killswitch/${data.archive_file.killswitch.output_md5}.zip"
  bucket = google_storage_bucket.function_source.name
  source = data.archive_file.killswitch.output_path
}

# --- Build identity (instead of the default compute service account) -------

# Project-level objectViewer: Cloud Functions copies the source zip into its
# own Google-created bucket (gcf-v2-sources-<number>-<region>) that doesn't
# exist before the first deploy, so a bucket-scoped grant can't be made ahead
# of time. mm-build-sa is used only for builds.
resource "google_project_iam_member" "build" {
  for_each = toset([
    "roles/logging.logWriter",
    "roles/artifactregistry.writer",
    "roles/storage.objectViewer",
  ])

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${local.build_sa.email}"
}

# --- The function -----------------------------------------------------------

resource "google_cloudfunctions2_function" "killswitch" {
  name     = "billing-killswitch"
  location = var.region

  build_config {
    runtime         = "python312"
    entry_point     = "handle_budget_alert"
    service_account = local.build_sa.id

    source {
      storage_source {
        bucket = google_storage_bucket.function_source.name
        object = google_storage_bucket_object.killswitch_source.name
      }
    }
  }

  service_config {
    service_account_email = local.killswitch_sa.email
    max_instance_count    = 1
    min_instance_count    = 0
    available_memory      = "256M"
    timeout_seconds       = 60
    ingress_settings      = "ALLOW_INTERNAL_ONLY"

    environment_variables = {
      PROJECT_ID = var.project_id
      DRY_RUN    = tostring(var.killswitch_dry_run)
    }
  }

  event_trigger {
    trigger_region        = var.region
    event_type            = "google.cloud.pubsub.topic.v1.messagePublished"
    pubsub_topic          = google_pubsub_topic.billing_alerts.id
    service_account_email = local.killswitch_sa.email
    # Retry until the unlink succeeds -- a transient API error must not
    # silently leave billing on past the budget.
    retry_policy = "RETRY_POLICY_RETRY"
  }

  depends_on = [
    google_project_service.killswitch,
    google_project_iam_member.build,
  ]
}

# --- Kill-switch permissions (least privilege) ------------------------------

# Project Billing Manager holds exactly create/deleteBillingAssignment on the
# project -- enough to unlink billing, no billing-account-wide rights.
resource "google_project_iam_member" "killswitch_billing" {
  project = var.project_id
  role    = "roles/billing.projectManager"
  member  = "serviceAccount:${local.killswitch_sa.email}"
}

# Eventarc delivers Pub/Sub messages as the kill-switch account.
resource "google_project_iam_member" "killswitch_event_receiver" {
  project = var.project_id
  role    = "roles/eventarc.eventReceiver"
  member  = "serviceAccount:${local.killswitch_sa.email}"
}

resource "google_cloud_run_service_iam_member" "killswitch_invoker" {
  location = var.region
  service  = google_cloudfunctions2_function.killswitch.service_config[0].service
  role     = "roles/run.invoker"
  member   = "serviceAccount:${local.killswitch_sa.email}"
}
