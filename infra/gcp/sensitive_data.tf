# Sensitive Data Protection (MM-115, ADR-0014/0015): masks personal and
# account data before text reaches the model or the RAG index. Free tier:
# 1 GiB of content inspection per month -- the demo uses a tiny fraction.

resource "google_project_service" "dlp" {
  service            = "dlp.googleapis.com"
  disable_on_destroy = false
}

# Components that send text to the model or index documents.
resource "google_project_iam_member" "runtime_dlp_user" {
  for_each = toset(["api", "agent", "mcp"])

  project = var.project_id
  role    = "roles/dlp.user"
  member  = "serviceAccount:${google_service_account.component[each.value].email}"

  depends_on = [google_project_service.dlp]
}
