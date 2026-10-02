# The API on Cloud Run (MM-123, ADR-0008): the same Docker Hub image as the
# AWS deployment, switched to the GCP adapters by environment variables.
#
# - Scales to zero (min 0): no cost while idle; the first request after idle
#   pays a cold start. Free tier covers the demo's traffic.
# - Runs as mm-api-sa: secrets from Secret Manager, Cloud SQL through the
#   built-in connection with IAM database login (DB_AUTH=iam, no password),
#   Gemini/Model Armor/SDP on Vertex, Pub/Sub publisher.
# - Public (allUsers may invoke): the app does its own auth -- NextAuth JWTs
#   for users, OIDC for internal callers (require_internal_caller).
# - CD (MM-G57) updates the image on every merge to main, so Terraform only
#   sets the first one and ignores later image changes.

locals {
  cloud_sql_connection = google_sql_database_instance.main.connection_name
  # Cloud Run's deterministic URL (name + project number + region): stable
  # even if the service is recreated, and known before it exists, so it can
  # be the OIDC audience and the target of push / scheduler / tasks (MM-124).
  api_base_url = "https://marginmaestro-api-${data.google_project.this.number}.${var.region}.run.app"

  api_env = {
    APP_ENV          = var.environment
    SECRETS_SOURCE   = "gcp"
    GCP_PROJECT_ID   = var.project_id
    GCP_LOCATION     = var.region
    MARKET_FEED_MODE = "live"

    DB_DIALECT = "postgres"
    DB_AUTH    = "iam"
    DB_HOST    = "/cloudsql/${local.cloud_sql_connection}"
    DB_PORT    = "5432"
    DB_NAME    = "marginmaestro"
    DB_USER    = trimsuffix(google_service_account.component["api"].email, ".gserviceaccount.com")

    LLM_PROVIDER         = "vertex"
    EMBEDDING_PROVIDER   = "vertex"
    VECTOR_STORE         = "pgvector"
    GUARDRAIL_PROVIDER   = "modelarmor"
    REDACTOR_PROVIDER    = "sdp"
    DOCUMENT_STORE       = "gcs"
    GCS_DOCUMENTS_BUCKET = google_storage_bucket.documents.name
    EVENT_BUS            = "pubsub"
    CLIENT_NOTIFIER      = "slack"

    # Internal callers (Pub/Sub push, Cloud Scheduler, Cloud Tasks) sign as
    # mm-invoker-sa, with the service's own URL as the audience (MM-124).
    INTERNAL_CALLER_SERVICE_ACCOUNT = google_service_account.component["invoker"].email
    INTERNAL_CALLER_AUDIENCE        = local.api_base_url

    # SLA timers (MM-122): one Cloud Tasks task per call, at its deadline.
    SLA_SCHEDULER     = "cloudtasks"
    INTERNAL_BASE_URL = local.api_base_url
    CLOUD_TASKS_QUEUE = google_cloud_tasks_queue.sla_checks.name

    CORS_ALLOWED_ORIGINS = var.frontend_origin

    # No OTLP collector on Cloud Run until Cloud Trace is wired (G5 story 4).
    OTEL_EXPORTER_OTLP_ENDPOINT = ""
  }
}

resource "google_project_service" "run" {
  service            = "run.googleapis.com"
  disable_on_destroy = false
}

resource "google_cloud_run_v2_service" "api" {
  name                = "marginmaestro-api"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    service_account                  = google_service_account.component["api"].email
    timeout                          = "600s" # an impact push runs the orchestrator (LLM calls)
    max_instance_request_concurrency = 20

    scaling {
      min_instance_count = 0
      max_instance_count = 4 # MM-124: 30 price pushes arrive at once every 5 minutes
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [local.cloud_sql_connection]
      }
    }

    containers {
      image = var.api_image

      ports {
        container_port = 8000
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
        cpu_idle          = true # CPU only while handling requests (cheapest)
        startup_cpu_boost = true
      }

      dynamic "env" {
        for_each = local.api_env
        content {
          name  = env.key
          value = env.value
        }
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }

      startup_probe {
        http_get {
          path = "/health"
        }
        initial_delay_seconds = 5
        period_seconds        = 5
        failure_threshold     = 24 # up to ~2 minutes for imports + first DB login
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].containers[0].image, client, client_version]
  }

  depends_on = [google_project_service.run]
}

resource "google_cloud_run_v2_service_iam_member" "api_public" {
  name     = google_cloud_run_v2_service.api.name
  location = google_cloud_run_v2_service.api.location
  role     = "roles/run.invoker"
  member   = "allUsers"
}

output "api_url" {
  description = "Stable HTTPS URL of the API on Cloud Run (BACKEND_API_URL for Vercel)"
  value       = local.api_base_url
}
