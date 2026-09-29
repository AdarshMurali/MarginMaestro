# App secrets in GCP Secret Manager (MM-101, ADR-0008).
#
# One JSON secret per environment, `marginmaestro-<environment>`, read by
# src/config/gcp_secret_manager.py when SECRETS_SOURCE=gcp. Same shape as the
# AWS secret `marginmaestro/<app_env>`.
#
# Terraform creates only the empty container and its IAM. Secret *values*
# are added out-of-band (`gcloud secrets versions add`), so they never land
# in Terraform state -- same rule as infra/secrets_manager.tf on AWS.

resource "google_project_service" "secretmanager" {
  service            = "secretmanager.googleapis.com"
  disable_on_destroy = false
}

resource "google_secret_manager_secret" "app" {
  secret_id = "marginmaestro-${var.environment}"

  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }

  depends_on = [google_project_service.secretmanager]
}

# Runtime accounts read this one secret only -- no project-wide accessor role.
resource "google_secret_manager_secret_iam_member" "runtime_reads_app_secret" {
  for_each = toset(local.runtime_accounts)

  secret_id = google_secret_manager_secret.app.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.component[each.value].email}"
}
