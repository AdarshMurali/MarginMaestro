# Cloud SQL for PostgreSQL (MM-108, ADR-0011) -- the first paid resource.
#
# Smallest shape: Enterprise edition, shared-core db-f1-micro, zonal, 10 GB
# SSD without autoresize (~$9-10/month, from trial credits). Stop it when idle
# with `demo_online = false` (storage is still billed; MM-120 switch).
#
# Access: public IP with NO authorized networks -- the only way in is the
# Cloud SQL Auth Proxy / Connector, which encrypts the connection and checks
# the caller's IAM identity (cloudsql.client) before any Postgres login.
#
# Logins:
# - built-in `postgres` user: migrations + seeding. Its password is set
#   out-of-band (`gcloud sql users set-password postgres --prompt-for-password`),
#   never through Terraform, so it never lands in state.
# - runtime service accounts: IAM database users (no passwords), granted the
#   `mm_app` role by persistence.db.grant_app_role (row-level security).

resource "google_project_service" "sqladmin" {
  service            = "sqladmin.googleapis.com"
  disable_on_destroy = false
}

resource "google_sql_database_instance" "main" {
  name             = "marginmaestro-pg"
  database_version = "POSTGRES_17"
  region           = var.region

  # Terraform-side guard; the API-side flag below guards console/gcloud deletes.
  deletion_protection = true

  settings {
    edition           = "ENTERPRISE"
    tier              = "db-f1-micro"
    availability_type = "ZONAL"
    disk_type         = "PD_SSD"
    disk_size         = 10
    disk_autoresize   = false
    activation_policy = var.demo_online ? "ALWAYS" : "NEVER"

    deletion_protection_enabled = true

    ip_configuration {
      ipv4_enabled = true
      # No authorized_networks: direct connections from any IP are refused.
      ssl_mode = "ENCRYPTED_ONLY"
    }

    backup_configuration {
      enabled                        = true
      start_time                     = "20:30" # UTC = 02:00 IST
      point_in_time_recovery_enabled = false   # extra storage cost; not needed for a demo
      backup_retention_settings {
        retained_backups = 7
      }
    }

    database_flags {
      name  = "cloudsql.iam_authentication"
      value = "on"
    }

    user_labels = {
      project    = "marginmaestro"
      managed-by = "terraform"
    }
  }

  depends_on = [google_project_service.sqladmin]
}

resource "google_sql_database" "app" {
  name     = "marginmaestro"
  instance = google_sql_database_instance.main.name
}

# Runtime service accounts log in with IAM (no passwords). Cloud SQL expects
# the email without the ".gserviceaccount.com" suffix.
resource "google_sql_user" "runtime" {
  for_each = toset(local.runtime_accounts)

  instance = google_sql_database_instance.main.name
  name     = trimsuffix(google_service_account.component[each.value].email, ".gserviceaccount.com")
  type     = "CLOUD_IAM_SERVICE_ACCOUNT"
}

resource "google_project_iam_member" "runtime_cloudsql" {
  for_each = {
    for pair in setproduct(local.runtime_accounts, ["roles/cloudsql.client", "roles/cloudsql.instanceUser"]) :
    "${pair[0]}:${pair[1]}" => { account = pair[0], role = pair[1] }
  }

  project = var.project_id
  role    = each.value.role
  member  = "serviceAccount:${google_service_account.component[each.value.account].email}"
}
