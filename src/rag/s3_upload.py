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


def iter_corpus_documents(settings: Settings | None = None) -> list[tuple[str, str]]:
    """Reads every .md document back from the bucket as (key, text) pairs --
    the read-side counterpart to upload_corpus(), used by ingestion (MM-24).
    """
    settings = settings or get_settings()
    if not settings.s3_documents_bucket:
        raise ValueError("S3_DOCUMENTS_BUCKET is not configured")
    if not settings.s3_documents_bucket_owner:
        raise ValueError("S3_DOCUMENTS_BUCKET_OWNER is not configured")

    client = boto3.client("s3")
    documents: list[tuple[str, str]] = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(
        Bucket=settings.s3_documents_bucket,
        ExpectedBucketOwner=settings.s3_documents_bucket_owner,
    ):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if not key.endswith(".md"):
                continue
            response = client.get_object(
                Bucket=settings.s3_documents_bucket,
                Key=key,
                ExpectedBucketOwner=settings.s3_documents_bucket_owner,
            )
            documents.append((key, response["Body"].read().decode("utf-8")))
    return documents
