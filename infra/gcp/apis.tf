# APIs the G0 foundation needs. Later phases add their own (Vertex AI,
# Cloud SQL, BigQuery, ...) in the story that first uses them, so nothing is
# enabled before it's needed. Enabling an API is free.
locals {
  foundation_apis = [
    "cloudresourcemanager.googleapis.com",
    "serviceusage.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "sts.googleapis.com",
    "storage.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "cloudtrace.googleapis.com",
  ]
}

resource "google_project_service" "foundation" {
  for_each = toset(local.foundation_apis)

  service = each.value

  # Keep APIs on if this config is destroyed -- turning an API off can break
  # resources managed elsewhere (e.g. the bootstrap state bucket).
  disable_on_destroy = false
}
