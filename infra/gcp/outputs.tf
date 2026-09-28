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
