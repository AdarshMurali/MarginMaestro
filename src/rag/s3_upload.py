from pathlib import Path

import boto3

from config.settings import Settings, get_settings


def upload_corpus(local_dir: Path, settings: Settings | None = None) -> list[str]:
    """Uploads every .md document under local_dir to the documents bucket,
    preserving its relative path as the S3 key. S3 is the source of truth
    for the corpus (citations, re-ingestion) -- ChromaDB only ever holds a
    derived, rebuildable index of it.
    """
    settings = settings or get_settings()
    if not settings.s3_documents_bucket:
        raise ValueError("S3_DOCUMENTS_BUCKET is not configured")
    if not settings.s3_documents_bucket_owner:
        raise ValueError("S3_DOCUMENTS_BUCKET_OWNER is not configured")

    client = boto3.client("s3")
    uploaded_keys: list[str] = []
    for path in sorted(local_dir.rglob("*.md")):
        key = path.relative_to(local_dir).as_posix()
        client.upload_file(
            str(path),
            settings.s3_documents_bucket,
            key,
            ExtraArgs={"ExpectedBucketOwner": settings.s3_documents_bucket_owner},
        )
        uploaded_keys.append(key)
    return uploaded_keys
