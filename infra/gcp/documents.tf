# RAG source documents (MM-111): the corpus's source of truth on GCP, the
# counterpart to the AWS S3 documents bucket. pgvector only holds a derived,
# rebuildable index of it. Tiny (~15 markdown files): inside the 5 GB free tier.
#
# No runtime service account reads it yet -- ingestion runs from the laptop
# (`python -m rag.gcs_documents data/documents`, then `python -m rag.ingest`
# with DOCUMENT_STORE=gcs). A scheduled re-ingestion job gets read access
# when one exists.

resource "google_storage_bucket" "documents" {
  name     = "${var.project_id}-documents"
  location = upper(var.region)

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  # Keep prior versions of a document: a CSA edit shouldn't silently erase
  # the text an earlier margin call cited. Old versions are pruned so the
  # bucket stays tiny.
  versioning {
    enabled = true
  }

  # MM-137 (ADR-0015): a document can't be deleted or replaced until it is
  # var.documents_retention_days old -- the text a margin call cited stays
  # available for that long. NOT locked on purpose: locking is irreversible
  # (the period could then never be shortened, nor the bucket deleted before
  # every object ages out). `python -m rag.gcs_documents` skips unchanged
  # files, so a re-upload only fails for a document edited inside the period.
  retention_policy {
    retention_period = var.documents_retention_days * 86400
    is_locked        = false
  }

  lifecycle_rule {
    condition {
      num_newer_versions = 5
      with_state         = "ARCHIVED"
    }
    action {
      type = "Delete"
    }
  }
}

output "documents_bucket" {
  description = "GCS bucket holding the RAG source documents (GCS_DOCUMENTS_BUCKET)"
  value       = google_storage_bucket.documents.name
}
