# One-time bootstrap: creates the GCS bucket that holds infra/gcp's remote
# Terraform state. Uses local state itself (the bucket can't store the state
# of its own creation) -- that local state is gitignored and only ever
# describes this one bucket.
terraform {
  required_version = ">= 1.15"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 8.4"
    }
  }

  backend "local" {
    path = "terraform.tfstate"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

resource "google_project_service" "storage" {
  service            = "storage.googleapis.com"
  disable_on_destroy = false
}

resource "google_storage_bucket" "tfstate" {
  name     = "${var.project_id}-tfstate"
  location = upper(var.region)

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  # Versioning lets a corrupted/overwritten state be rolled back. Old
  # versions are pruned to stay far inside the 5 GB always-free quota.
  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      num_newer_versions = 10
      with_state         = "ARCHIVED"
    }
    action {
      type = "Delete"
    }
  }

  labels = {
    project    = "marginmaestro"
    managed-by = "terraform"
  }

  depends_on = [google_project_service.storage]
}
