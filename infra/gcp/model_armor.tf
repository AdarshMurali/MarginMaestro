# Model Armor (MM-114, ADR-0014): the content-screening engine Agent Platform
# uses. One template screens every LLM prompt and response (via the app's
# guardrail pipeline now; attached to Agent Gateway in G5 -- same template).
# Free tier: 2M tokens/month, then $0.10 per 1M tokens.

resource "google_project_service" "modelarmor" {
  service            = "modelarmor.googleapis.com"
  disable_on_destroy = false
}

resource "google_model_armor_template" "llm_traffic" {
  location    = var.region
  template_id = "marginmaestro-llm-traffic"

  filter_config {
    # Prompt injection / jailbreak: the main threat for a RAG agent reading
    # untrusted CSA chunks and client replies.
    pi_and_jailbreak_filter_settings {
      filter_enforcement = "ENABLED"
      confidence_level   = "MEDIUM_AND_ABOVE"
    }

    malicious_uri_filter_settings {
      filter_enforcement = "ENABLED"
    }

    # Responsible-AI content filters, on both prompts and responses.
    rai_settings {
      dynamic "rai_filters" {
        for_each = ["HATE_SPEECH", "HARASSMENT", "SEXUALLY_EXPLICIT", "DANGEROUS"]
        content {
          filter_type      = rai_filters.value
          confidence_level = "MEDIUM_AND_ABOVE"
        }
      }
    }
  }

  labels = {
    project    = "marginmaestro"
    managed-by = "terraform"
  }

  depends_on = [google_project_service.modelarmor]
}

# Components that call the model screen through the template.
resource "google_project_iam_member" "runtime_modelarmor_user" {
  for_each = toset(["api", "agent", "mcp"])

  project = var.project_id
  role    = "roles/modelarmor.user"
  member  = "serviceAccount:${google_service_account.component[each.value].email}"

  depends_on = [google_project_service.modelarmor]
}

output "model_armor_template" {
  description = "Model Armor template resource name (MODEL_ARMOR_TEMPLATE)"
  value       = google_model_armor_template.llm_traffic.id
}
