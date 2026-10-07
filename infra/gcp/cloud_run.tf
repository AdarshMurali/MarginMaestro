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

    # G6 (ADR-0016): client notices on WhatsApp once var.client_notifier is
    # flipped; Slack carries internal traffic. The token, recipient, app
    # secret and verify token are keys in the JSON secret, not env vars.
    # Meta calls POST {api_base_url}/webhooks/whatsapp (public, HMAC-signed).
    CLIENT_NOTIFIER            = var.client_notifier
    INTERNAL_NOTIFIER          = var.internal_notifier
    WHATSAPP_PHONE_NUMBER_ID   = var.whatsapp_phone_number_id
    WHATSAPP_TEMPLATE_NAME     = var.whatsapp_template_name
    WHATSAPP_TEMPLATE_LANGUAGE = var.whatsapp_template_language
    WHATSAPP_GRAPH_VERSION     = var.whatsapp_graph_version
    # MM-144: the personalised PDF notice (template v2); off until Meta approves v2.
    WHATSAPP_NOTICE_PDF        = var.whatsapp_notice_pdf
    WHATSAPP_PDF_TEMPLATE_NAME = var.whatsapp_pdf_template_name

    # Internal callers (Pub/Sub push, Cloud Scheduler, Cloud Tasks) sign as
    # mm-invoker-sa, with the service's own URL as the audience (MM-124).
    INTERNAL_CALLER_SERVICE_ACCOUNT = google_service_account.component["invoker"].email
    INTERNAL_CALLER_AUDIENCE        = local.api_base_url

    # SLA timers (MM-122): one Cloud Tasks task per call, at its deadline.
    SLA_SCHEDULER     = "cloudtasks"
    INTERNAL_BASE_URL = local.api_base_url
    CLOUD_TASKS_QUEUE = google_cloud_tasks_queue.sla_checks.name

    # Vercel and Firebase App Hosting (MM-145) serve the same frontend.
    CORS_ALLOWED_ORIGINS = join(",", local.frontend_origins)

    # MM-146 (ADR-0021): a status doc per margin call in Firestore, pushed to
    # subscribed browsers; GET /realtime/token signs Firebase custom tokens as
    # mm-api-sa (datastore.user + tokenCreator on itself, firebase.tf).
    REALTIME              = var.realtime
    FIRESTORE_DATABASE    = google_firestore_database.default.name
    FIREBASE_TOKEN_SIGNER = google_service_account.component["api"].email

    # Traces go to Cloud Trace (MM-127); mm-api-sa has roles/cloudtrace.agent.
    TRACE_EXPORTER = "cloudtrace"

    # "Ask the margin desk" (MM-129): chat is on once the agent is deployed
    # and its resource name is set. mm-api-sa's aiplatform.user covers the
    # reasoningEngines query/streamQuery calls.
    DESK_ASSISTANT      = var.desk_agent_resource == "" ? "none" : "agent_runtime"
    DESK_AGENT_RESOURCE = var.desk_agent_resource

    # Data governance (G8, ADR-0015): confidential catalog values never reach
    # the model unmasked (MM-135), and every margin call emits lineage to the
    # Data Lineage API (MM-136; mm-api-sa has roles/datalineage.producer).
    LLM_DATA_CLASS_FILTER = "catalog"
    LINEAGE_EXPORTER      = var.lineage_exporter
    LINEAGE_LOCATION      = var.region

    # G7 (ADR-0013): the BigQuery warehouse -- the live book's daily load after
    # the margin run, and the /reports page (mm-api-sa: dataEditor on the
    # dataset, jobUser, fine-grained reader; bigquery.tf).
    WAREHOUSE         = var.warehouse
    WAREHOUSE_DATASET = google_bigquery_dataset.analytics.dataset_id
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
    # The image and the revision labels belong to CD (deploy-cloudrun).
    ignore_changes = [template[0].containers[0].image, template[0].labels, client, client_version]
  }

  depends_on = [google_project_service.run]
}

resource "google_cloud_run_v2_service_iam_member" "api_public" {
  name     = google_cloud_run_v2_service.api.name
  location = google_cloud_run_v2_service.api.location
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# CD (MM-126): GitHub Actions, as mm-ci-sa, may deploy new revisions of this
# one service -- run.developer scoped to the service, not the project -- and
# run them as mm-api-sa (actAs on that one account). It can't create other
# services, change IAM, or act as any other identity.
resource "google_cloud_run_v2_service_iam_member" "ci_deployer" {
  name     = google_cloud_run_v2_service.api.name
  location = google_cloud_run_v2_service.api.location
  role     = "roles/run.developer"
  member   = "serviceAccount:${google_service_account.component["ci"].email}"
}

resource "google_service_account_iam_member" "ci_acts_as_api" {
  service_account_id = google_service_account.component["api"].name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.component["ci"].email}"
}

output "api_url" {
  description = "Stable HTTPS URL of the API on Cloud Run (BACKEND_API_URL for Vercel)"
  value       = local.api_base_url
}

output "whatsapp_webhook_url" {
  description = "Callback URL to register in the Meta app dashboard (WhatsApp > Configuration), MM-133"
  value       = "${local.api_base_url}/webhooks/whatsapp"
}
