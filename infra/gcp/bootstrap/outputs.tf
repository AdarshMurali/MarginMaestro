output "tfstate_bucket" {
  description = "Bucket name to use in infra/gcp/backend.tf"
  value       = google_storage_bucket.tfstate.name
}
