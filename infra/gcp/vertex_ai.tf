# Vertex AI for Gemini (MM-109, ADR-0009): reasoning/drafting + embeddings.
# Billed per token -- no always-on cost. Local dev calls it with your own ADC
# (project owner); deployed services use their runtime service accounts.

resource "google_project_service" "aiplatform" {
  service            = "aiplatform.googleapis.com"
  disable_on_destroy = false
}

# Only the components that call the model: the API (simulate/draft paths),
# the orchestrator (agents) and the MCP servers (RAG embeddings).
resource "google_project_iam_member" "runtime_vertex_user" {
  for_each = toset(["api", "agent", "mcp"])

  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.component[each.value].email}"

  depends_on = [google_project_service.aiplatform]
}
