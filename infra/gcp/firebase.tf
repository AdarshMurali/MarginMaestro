# Firebase (ADR-0021): MM-145 hosts the Next.js frontend on Firebase App
# Hosting (Vercel stays up -- same backend), MM-146 pushes margin-call status
# to browsers through Firestore.
#
# Firebase itself was added to the project in the console (2026-10-07);
# google_firebase_project is beta-only and is not managed here.
#
# Cost (all inside always-free / no-cost quotas at demo scale):
# - Firestore: 1 GiB stored, 50k reads / 20k writes / 20k deletes per day free.
#   One small doc per margin call, one write per lifecycle step: ~$0.
# - Firebase Auth (custom-token sign-in): free; no Identity Platform upgrade.
# - App Hosting: a Cloud Run service at min 0 instances (free tier), one Cloud
#   Build per push to main (2,500 free build-minutes/month; a Next.js build is
#   ~4-6 min), the image in a Google-managed Artifact Registry repo (0.5 GB
#   free, then $0.10/GB-month), and egress (10 GiB/month no-cost). Expected
#   ~$0-0.10/month; see docs/gcp/adr/0021-firebase-firestore-realtime.md.
#
# App Hosting needs a one-time GitHub authorization that Terraform can't do:
#   1. apply with app_hosting_github_connected = false (the default) -- this
#      creates the Developer Connect connection;
#   2. open the `app_hosting_github_authorization` output's action_uri and
#      install the Firebase GitHub app on AdarshMurali/MarginMaestro;
#   3. set app_hosting_github_connected = true (and app_hosting_web_app_id) and
#      apply again -- this creates the repository link, the backend and its
#      automatic rollouts from main.

locals {
  firebase_apis = [
    "firebase.googleapis.com",
    "firestore.googleapis.com",
    "firebaserules.googleapis.com",
    "identitytoolkit.googleapis.com",
    "firebaseapphosting.googleapis.com",
    "developerconnect.googleapis.com",
  ]

  # App Hosting's default domain: <backend>--<project>.<region>.hosted.app.
  app_hosting_url = "https://${var.app_hosting_backend_id}--${var.project_id}.${var.region}.hosted.app"

  # Browser origins the API's CORS policy allows: Vercel and App Hosting.
  frontend_origins = distinct(concat(var.frontend_origins, [local.app_hosting_url]))

  app_hosting_enabled = var.app_hosting_github_connected && var.app_hosting_web_app_id != ""

  # Frontend secrets App Hosting reads by name (frontend/apphosting.yaml).
  # Values are added out-of-band, never in Terraform.
  frontend_secrets = {
    auth_secret         = "mm-frontend-auth-secret"         # AUTH_SECRET (NextAuth cookies)
    auth_backend_secret = "mm-frontend-auth-backend-secret" # AUTH_BACKEND_SECRET (API JWTs)
  }
}

resource "google_project_service" "firebase" {
  for_each = toset(local.firebase_apis)

  service            = each.value
  disable_on_destroy = false
}

# --- MM-146: Firestore real-time call status ---------------------------------------

# The free tier applies to the project's (default) database. Regional, in the
# same region as everything else.
resource "google_firestore_database" "default" {
  name                    = "(default)"
  location_id             = var.region
  type                    = "FIRESTORE_NATIVE"
  delete_protection_state = "DELETE_PROTECTION_ENABLED"
  deletion_policy         = "ABANDON"

  depends_on = [google_project_service.firebase]
}

# Security rules: browsers read only their counterparties' status docs, never
# write (firebase/firestore.rules).
resource "google_firebaserules_ruleset" "firestore" {
  source {
    files {
      name    = "firestore.rules"
      content = file("${path.module}/../../firebase/firestore.rules")
    }
  }

  lifecycle {
    create_before_destroy = true
  }

  depends_on = [google_firestore_database.default]
}

resource "google_firebaserules_release" "firestore" {
  name         = "cloud.firestore"
  ruleset_name = "projects/${var.project_id}/rulesets/${google_firebaserules_ruleset.firestore.name}"

  lifecycle {
    replace_triggered_by = [google_firebaserules_ruleset.firestore]
  }
}

# The API writes status docs (server-side IAM access; rules don't apply to it).
resource "google_project_iam_member" "api_firestore_user" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.component["api"].email}"
}

# GET /realtime/token signs Firebase custom tokens as mm-api-sa through the
# IAM signBlob API -- on itself only, no key file.
resource "google_service_account_iam_member" "api_signs_firebase_tokens" {
  service_account_id = google_service_account.component["api"].name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_service_account.component["api"].email}"
}

# --- MM-145: Firebase App Hosting for the frontend -----------------------------------

resource "google_service_account" "app_hosting" {
  account_id   = "mm-apphosting-sa"
  display_name = "MarginMaestro frontend (Firebase App Hosting)"

  depends_on = [google_project_service.foundation]
}

resource "google_project_iam_member" "app_hosting_compute_runner" {
  project = var.project_id
  role    = "roles/firebaseapphosting.computeRunner"
  member  = "serviceAccount:${google_service_account.app_hosting.email}"
}

resource "google_secret_manager_secret" "frontend" {
  for_each = local.frontend_secrets

  secret_id = each.value

  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }

  depends_on = [google_project_service.secretmanager]
}

# App Hosting reads each secret at build and run time as its backend service
# account: accessor (the value) + viewer (the metadata), on these secrets only.
resource "google_secret_manager_secret_iam_member" "app_hosting_reads_frontend_secrets" {
  for_each = {
    for pair in setproduct(keys(local.frontend_secrets), [
      "roles/secretmanager.secretAccessor",
      "roles/secretmanager.viewer",
    ]) : "${pair[0]}:${pair[1]}" => { secret = pair[0], role = pair[1] }
  }

  secret_id = google_secret_manager_secret.frontend[each.value.secret].id
  role      = each.value.role
  member    = "serviceAccount:${google_service_account.app_hosting.email}"
}

# Developer Connect stores the GitHub OAuth token it receives as a secret in
# this project, as its own service agent (Google's documented requirement for
# a GitHub connection). Reviewed Checkov skip, scoped to this one binding: the
# member is a Google-managed service agent (not one of ours), and Developer
# Connect needs to create the token secret and set its IAM.
resource "google_project_iam_member" "developer_connect_secrets" {
  #checkov:skip=CKV_GCP_42:Google-managed Developer Connect service agent; Google's documented requirement for a GitHub connection (ADR-0021)
  project = var.project_id
  role    = "roles/secretmanager.admin"
  member  = "serviceAccount:service-${data.google_project.this.number}@gcp-sa-devconnect.iam.gserviceaccount.com"

  depends_on = [google_project_service.firebase]
}

# The GitHub connection, via the Firebase GitHub app. Created pending; the
# user authorizes it once in the browser (output app_hosting_github_authorization).
resource "google_developer_connect_connection" "github" {
  location      = var.region
  connection_id = "marginmaestro-github"

  github_config {
    github_app = "FIREBASE"
  }

  depends_on = [google_project_iam_member.developer_connect_secrets]
}

resource "google_developer_connect_git_repository_link" "frontend" {
  count = local.app_hosting_enabled ? 1 : 0

  location               = var.region
  git_repository_link_id = "marginmaestro"
  parent_connection      = google_developer_connect_connection.github.connection_id
  clone_uri              = "https://github.com/${var.github_repository}.git"
}

resource "google_firebase_app_hosting_backend" "frontend" {
  count = local.app_hosting_enabled ? 1 : 0

  location         = var.region
  backend_id       = var.app_hosting_backend_id
  app_id           = var.app_hosting_web_app_id
  display_name     = "MarginMaestro frontend"
  serving_locality = "GLOBAL_ACCESS"
  service_account  = google_service_account.app_hosting.email

  codebase {
    repository     = google_developer_connect_git_repository_link.frontend[0].name
    root_directory = "/frontend"
  }

  depends_on = [
    google_project_iam_member.app_hosting_compute_runner,
    google_secret_manager_secret_iam_member.app_hosting_reads_frontend_secrets,
  ]
}

# Automatic rollouts: every push to main builds and deploys the frontend.
resource "google_firebase_app_hosting_traffic" "frontend" {
  count = local.app_hosting_enabled ? 1 : 0

  location = var.region
  backend  = google_firebase_app_hosting_backend.frontend[0].backend_id

  rollout_policy {
    codebase_branch = "main"
    disabled        = !var.app_hosting_auto_rollout
  }
}

output "app_hosting_url" {
  description = "Firebase App Hosting default URL of the frontend (MM-145)"
  value       = local.app_hosting_url
}

output "app_hosting_github_authorization" {
  description = "Open action_uri once to authorize the Firebase GitHub app (stage PENDING_USER_OAUTH / PENDING_INSTALL_APP), then set app_hosting_github_connected = true"
  value       = google_developer_connect_connection.github.installation_state
}

output "frontend_secret_ids" {
  description = "Secret Manager secrets App Hosting reads (values added out-of-band)"
  value       = { for k, s in google_secret_manager_secret.frontend : k => s.secret_id }
}
