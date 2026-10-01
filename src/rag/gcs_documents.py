"""RAG source documents in Google Cloud Storage (MM-111) -- the GCP
counterpart to rag.s3_upload. The bucket is the corpus's source of truth
(citations, re-ingestion); pgvector only holds a derived, rebuildable index.

Upload once from the repo:  python -m rag.gcs_documents data/documents
"""

import sys
from pathlib import Path
from typing import Any

from config.settings import Settings, get_settings


def _bucket(settings: Settings, client: Any | None) -> Any:
    if not settings.gcs_documents_bucket:
        raise ValueError("GCS_DOCUMENTS_BUCKET is not configured")
    if client is None:
        # Imported lazily: only needed when DOCUMENT_STORE=gcs.
        from google.cloud.storage import Client

        client = Client(project=settings.gcp_project_id)
    return client.bucket(settings.gcs_documents_bucket)


def upload_corpus(
    local_dir: Path, settings: Settings | None = None, client: Any | None = None
) -> list[str]:
    """Uploads every .md document under local_dir, keeping its relative path
    as the object name (e.g. `csa/CP-3.md`, which ingestion turns into
    doc_type=csa, counterparty_id=CP-3)."""
    settings = settings or get_settings()
    bucket = _bucket(settings, client)
    names: list[str] = []
    for path in sorted(local_dir.rglob("*.md")):
        name = path.relative_to(local_dir).as_posix()
        bucket.blob(name).upload_from_filename(str(path), content_type="text/markdown")
        names.append(name)
    return names


def iter_corpus_documents(
    settings: Settings | None = None, client: Any | None = None
) -> list[tuple[str, str]]:
    """Every .md document in the bucket as (object name, text)."""
    settings = settings or get_settings()
    bucket = _bucket(settings, client)
    return [
        (blob.name, blob.download_as_text(encoding="utf-8"))
        for blob in sorted(bucket.list_blobs(), key=lambda b: b.name)
        if blob.name.endswith(".md")
    ]


def main(argv: list[str]) -> None:
    local_dir = Path(argv[0] if argv else "data/documents")
    names = upload_corpus(local_dir)
    print(f"Uploaded {len(names)} documents to gs://{get_settings().gcs_documents_bucket}/")


if __name__ == "__main__":
    main(sys.argv[1:])
