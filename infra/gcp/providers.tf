terraform {
  required_version = ">= 1.15"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 8.4"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.7"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region

  # The Billing Budgets API rejects end-user credentials (ADC) unless the
  # request names a quota project -- bill API quota to this project.
  user_project_override = true
  billing_project       = var.project_id

  default_labels = {
    project     = "marginmaestro"
    managed-by  = "terraform"
    environment = var.environment
  }
}
