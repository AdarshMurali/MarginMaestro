variable "project_id" {
  description = "GCP project that owns the Terraform state bucket"
  type        = string
  default     = "marginmaestro-demo"
}

variable "region" {
  description = "Bucket region. us-central1 keeps it inside Cloud Storage's always-free tier (US regions only)."
  type        = string
  default     = "us-central1"
}
