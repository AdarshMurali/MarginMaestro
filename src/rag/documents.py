"""Where RAG source documents are read from (MM-111): DOCUMENT_STORE=s3
(default -- the AWS deployment, unchanged) or gcs (the GCP track)."""

from config.settings import Settings, get_settings


def iter_corpus_documents(settings: Settings | None = None) -> list[tuple[str, str]]:
    settings = settings or get_settings()
    store = settings.document_store.strip().lower()
    if store == "gcs":
        from rag import gcs_documents

        return gcs_documents.iter_corpus_documents(settings)
    if store == "s3":
        from rag import s3_upload

        return s3_upload.iter_corpus_documents(settings)
    raise ValueError(
        f"DOCUMENT_STORE must be one of ('s3', 'gcs'), got {settings.document_store!r}"
    )
