# Read-only MCP servers on Cloud Run (MM-128): the tools the desk assistant
# (MM-129, Agent Runtime) picks at runtime. One service per server, so IAM
# decides per tool set who may call it:
#
# - Private: no allUsers. Only mm-agent-sa may invoke (MM-131 moves this to
#   the agent's own Agent Identity principal). Cloud Run checks the caller's
#   Google ID token before a request reaches the container.
# - The analyst arrives in the X-MM-User header and is trusted only because
#   of that IAM check; the role and scope come from the database, and reads
#   run under row-level security (mcp_servers/caller.py).
# - Read-only by construction: the notifier servers (Slack, ServiceNow) are
#   never deployed, so no LLM can reach a client outside the approval gate.
# - Scale to zero, CPU only during requests: $0 while idle, demo traffic
#   stays inside the Cloud Run free tier.
# - Same Docker Hub image as the API; only the command differs. CD (MM-126)
#   rolls the image, so Terraform ignores later image changes.

locals {
  mcp_servers = {
    "market-data"   = { memory = "512Mi" }
    "rag"           = { memory = "512Mi" }
    "margin-status" = { memory = "1Gi" } # imports the orchestrator to read its checkpoints
  }

  mcp_env = {
    APP_ENV = var.environment
    # No secrets needed (IAM DB login, Vertex via the service account), so
    # the MCP services never load the app secret's Slack/ServiceNow tokens.
    SECRETS_SOURCE   = "env"
    GCP_PROJECT_ID   = var.project_id
    GCP_LOCATION     = var.region
    MARKET_FEED_MODE = "live"

    DB_DIALECT = "postgres"
    DB_AUTH    = "iam"
    DB_HOST    = "/cloudsql/${local.cloud_sql_connection}"
    DB_PORT    = "5432"
    DB_NAME    = "marginmaestro"
    DB_USER    = trimsuffix(google_service_account.component["mcp"].email, ".gserviceaccount.com")

    LLM_PROVIDER       = "vertex"
    EMBEDDING_PROVIDER = "vertex"
    VECTOR_STORE       = "pgvector"
  }
}

resource "google_cloud_run_v2_service" "mcp" {
  for_each = local.mcp_servers

  name                = "mcp-${each.key}"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL" # Agent Runtime calls over the public URL; IAM gates it
  deletion_protection = false

  template {
    service_account                  = google_service_account.component["mcp"].email
    timeout                          = "60s"
    max_instance_request_concurrency = 10

    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [local.cloud_sql_connection]
      }
    }

    containers {
      image   = var.api_image
      command = ["python", "-m", "mcp_servers.http"]
      args    = [each.key]

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "1"
          memory = each.value.memory
        }
        cpu_idle          = true
        startup_cpu_boost = true
      }

      dynamic "env" {
        for_each = local.mcp_env
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
        failure_threshold     = 24
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].containers[0].image, template[0].labels, client, client_version]
  }

  depends_on = [google_project_service.run]
}

# The desk assistant's identity is the only invoker.
resource "google_cloud_run_v2_service_iam_member" "mcp_agent_invoker" {
  for_each = google_cloud_run_v2_service.mcp

  name     = each.value.name
  location = each.value.location
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.component["agent"].email}"
}

# CD (MM-126) rolls new images to these services too, running as mm-mcp-sa.
resource "google_cloud_run_v2_service_iam_member" "mcp_ci_deployer" {
  for_each = google_cloud_run_v2_service.mcp

  name     = each.value.name
  location = each.value.location
  role     = "roles/run.developer"
  member   = "serviceAccount:${google_service_account.component["ci"].email}"
}

resource "google_service_account_iam_member" "ci_acts_as_mcp" {
  service_account_id = google_service_account.component["mcp"].name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.component["ci"].email}"
}

output "mcp_urls" {
  description = "MCP endpoints (POST <url>/mcp) for the desk assistant, by server"
  value       = { for name, service in google_cloud_run_v2_service.mcp : name => "${service.uri}/mcp" }
}
