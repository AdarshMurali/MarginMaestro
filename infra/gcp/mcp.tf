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
# - Same Docker Hub image as the API; only the command (uvicorn on
#   mcp_servers.http:create_app) and MCP_SERVER differ. CD (MM-126)
#   rolls the image, so Terraform ignores later image changes.

locals {
  mcp_servers = {
    "market-data"   = { memory = "512Mi" }
    "rag"           = { memory = "512Mi" }
    "margin-status" = { memory = "1Gi" } # imports the orchestrator to read its checkpoints
  }

  # Deterministic hostnames (like the API's, MM-124): known before the
  # services exist, so each can allow only its own Host header
  # (DNS-rebinding protection stays on). Callers must use these URLs.
  mcp_hosts = {
    for name in keys(local.mcp_servers) :
    name => "mcp-${name}-${data.google_project.this.number}.${var.region}.run.app"
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
      command = ["uvicorn"]
      args    = ["--factory", "mcp_servers.http:create_app", "--host", "0.0.0.0", "--port", "8080"]

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
        for_each = merge(local.mcp_env, {
          MCP_SERVER        = each.key
          MCP_ALLOWED_HOSTS = local.mcp_hosts[each.key]
        })
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

# mm-agent-sa, the desk assistant's identity before Agent Identity (MM-131).
# Kept only during the cutover; agent_identity.tf grants the agent principal.
resource "google_cloud_run_v2_service_iam_member" "mcp_agent_invoker" {
  for_each = var.mcp_legacy_sa_invoker ? google_cloud_run_v2_service.mcp : {}

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
  value       = { for name, host in local.mcp_hosts : name => "https://${host}/mcp" }
}
