# Workload Identity Federation for GitHub Actions (MM-100, ADR-0008).
#
# CI logs in to GCP as mm-ci-sa without a stored key: each job asks GitHub
# for a short-lived OIDC token, GCP verifies GitHub's signature and the
# condition below, and returns a short-lived access token for mm-ci-sa.
#
# Only this repository, on main, is trusted. The condition matches GitHub's
# numeric repository and owner IDs (not names), so a renamed repo -- or a new
# repo re-created under the same name -- can't inherit access.
#
# mm-ci-sa gets no project roles here; the Cloud Run deploy roles are granted
# with the deploy job in G5 (MM-G57). Images stay on Docker Hub (ADR-0017).

resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "github"
  display_name              = "GitHub Actions"
  description               = "OIDC identities from GitHub Actions workflows"

  depends_on = [google_project_service.foundation]
}

resource "google_iam_workload_identity_pool_provider" "github_actions" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-actions"
  display_name                       = "GitHub Actions OIDC"
  description                        = "Trusts tokens from ${var.github_repository} (by ID) on ${var.github_deploy_ref} only"

  attribute_mapping = {
    "google.subject"                = "assertion.sub"
    "attribute.repository"          = "assertion.repository"
    "attribute.repository_id"       = "assertion.repository_id"
    "attribute.repository_owner_id" = "assertion.repository_owner_id"
    "attribute.ref"                 = "assertion.ref"
  }

  attribute_condition = join(" && ", [
    "assertion.repository_id == '${var.github_repository_id}'",
    "assertion.repository_owner_id == '${var.github_repository_owner_id}'",
    "assertion.ref == '${var.github_deploy_ref}'",
  ])

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

# Lets identities from this repository (and only this one) act as mm-ci-sa.
resource "google_service_account_iam_member" "ci_workload_identity_user" {
  service_account_id = google_service_account.component["ci"].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository_id/${var.github_repository_id}"
}
