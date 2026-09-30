output "project_id" {
  value = var.project_id
}

output "region" {
  value = var.region
}

output "service_account_emails" {
  description = "Service account email per component"
  value       = { for k, sa in google_service_account.component : k => sa.email }
}

output "github_wif_provider" {
  description = "Workload Identity provider for google-github-actions/auth -- set as the GitHub Actions variable GCP_WIF_PROVIDER"
  value       = google_iam_workload_identity_pool_provider.github_actions.name
}

output "github_ci_service_account" {
  description = "Service account CI impersonates -- set as the GitHub Actions variable GCP_CI_SERVICE_ACCOUNT"
  value       = google_service_account.component["ci"].email
}

output "app_secret_id" {
  description = "Secret Manager secret holding the app's JSON config (values added out-of-band)"
  value       = google_secret_manager_secret.app.id
}

output "cloudsql_connection_name" {
  description = "Instance connection name for the Cloud SQL Auth Proxy / Connector"
  value       = google_sql_database_instance.main.connection_name
}

output "cloudsql_runtime_db_users" {
  description = "IAM database users for the runtime service accounts"
  value       = [for u in google_sql_user.runtime : u.name]
}
