# Data governance (Phase G8, ADR-0015) -- everything except the catalog
# entries (dataplex.tf). BigQuery parts (policy tags, row access, table
# expiration, data-quality scans) are parked with Phase G7.

# --- Lineage per margin call (MM-136) -----------------------------------------
# The API (which runs the orchestrator) sends one OpenLineage event per call
# milestone to processOpenLineageRunEvent (src/governance/lineage.py).
#
# Cost: lineage metadata counts toward catalog metadata storage -- free up to
# 1 MiB monthly average, then $2/GiB-month. A call is 3-4 events of ~12 links;
# demo volume (a few calls a day) stays in the free MiB or costs cents at
# worst. Lineage for custom events is not billed per API call; the premium
# processing SKU applies to automatic BigQuery/Dataproc lineage, not used here.

resource "google_project_service" "datalineage" {
  service            = "datalineage.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_iam_member" "api_lineage_producer" {
  project = var.project_id
  role    = "roles/datalineage.producer"
  member  = "serviceAccount:${google_service_account.component["api"].email}"

  depends_on = [google_project_service.datalineage]
}

# --- Cloud Audit Logs: data access (MM-137) -----------------------------------
# Admin Activity logs are always on (free). This adds Data Access logs --
# who read or wrote data -- for the three services that hold it.
#
# Volume estimate (50 GiB/month of logs ingested is free per project):
# - Secret Manager: one AccessSecretVersion per API cold start (the MCP
#   services read no secret) -- hundreds a month.
# - Cloud Storage: the documents bucket is read on re-ingestion only, plus
#   Terraform state reads/writes on every plan/apply -- hundreds a month.
# - Cloud SQL: the API-level calls (connector certificate refresh, connect,
#   instance gets) -- roughly one an hour per running instance. These are NOT
#   per-query logs: SQL statement auditing (pgaudit) needs a database flag and
#   is deliberately not enabled (it would log every query).
# At ~1-2 KB an entry that is well under 100 MB/month: no risk to the free
# tier, so DATA_READ + DATA_WRITE (+ ADMIN_READ) are on for all three.
#
# Note: google_project_iam_audit_config is authoritative per service -- a
# setting made for these services in the console is replaced on apply.

locals {
  audited_services = [
    "cloudsql.googleapis.com",
    "storage.googleapis.com",
    "secretmanager.googleapis.com",
  ]
}

resource "google_project_iam_audit_config" "data_access" {
  for_each = toset(local.audited_services)

  project = var.project_id
  service = each.value

  audit_log_config {
    log_type = "ADMIN_READ"
  }
  audit_log_config {
    log_type = "DATA_READ"
  }
  audit_log_config {
    log_type = "DATA_WRITE"
  }
}

# --- Sensitive Data Protection inspection of the documents bucket (MM-137) ----
# A scheduled inspection job over gs://<project>-documents (the RAG corpus):
# personal / account identifiers that should never be in a CSA or policy
# document. Findings: the job's summary (Console > Sensitive Data Protection >
# Inspection > Jobs, or `python -m governance.sdp_scan`, which logs it), the
# finding_count metric in Cloud Monitoring (publish_to_stackdriver), and an
# email to the project owners when a run finishes.
#
# Cost: storage inspection is free up to 1 GB a month, then $1/GB. The corpus
# is ~15 markdown files (< 100 KB), scanned every var.sdp_scan_period_days:
# $0. Nothing is saved to BigQuery (parked with G7) and nothing is
# de-identified in place.
#
# The DLP service agent needs to read the bucket.

locals {
  sdp_info_types = [
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "CREDIT_CARD_NUMBER",
    "IBAN_CODE",
    "SWIFT_CODE",
    "US_BANK_ROUTING_MICR",
    "US_SOCIAL_SECURITY_NUMBER",
    "PERSON_NAME",
  ]
  dlp_service_agent = "service-${data.google_project.this.number}@dlp-api.iam.gserviceaccount.com"
}

resource "google_storage_bucket_iam_member" "dlp_reads_documents" {
  bucket = google_storage_bucket.documents.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${local.dlp_service_agent}"

  depends_on = [google_project_service.dlp]
}

resource "google_data_loss_prevention_job_trigger" "documents_scan" {
  parent       = "projects/${var.project_id}/locations/${var.region}"
  trigger_id   = "marginmaestro-documents-scan"
  display_name = "MarginMaestro documents scan"
  description  = "Inspects the RAG source documents for personal and account identifiers (MM-137, ADR-0015)."

  triggers {
    schedule {
      recurrence_period_duration = "${var.sdp_scan_period_days * 86400}s"
    }
  }

  inspect_job {
    storage_config {
      cloud_storage_options {
        file_set {
          url = "gs://${google_storage_bucket.documents.name}/**"
        }
      }
    }

    inspect_config {
      # PERSON_NAME is reported here (unlike the LLM redactor, which skips it
      # because counterparty names are needed): the scan surfaces where the
      # corpus names people or firms, which the data-class filter
      # pseudonymizes before any prompt (MM-135).
      dynamic "info_types" {
        for_each = local.sdp_info_types
        content {
          name = info_types.value
        }
      }
      min_likelihood = "LIKELY"
      include_quote  = false # findings carry the location, not the value
    }

    actions {
      publish_to_stackdriver {}
    }
    actions {
      job_notification_emails {}
    }
  }

  depends_on = [google_storage_bucket_iam_member.dlp_reads_documents]
}

output "sdp_documents_scan_trigger" {
  description = "Sensitive Data Protection job trigger scanning the documents bucket (MM-137); run on demand from the console (Run now) or the API (jobTriggers.activate)"
  value       = google_data_loss_prevention_job_trigger.documents_scan.name
}
