import boto3
import pytest
from moto import mock_aws

from config.settings import Settings
from rag.s3_upload import iter_corpus_documents, upload_corpus


@pytest.fixture
def corpus_dir(tmp_path):
    csa_dir = tmp_path / "csa"
    csa_dir.mkdir()
    (csa_dir / "CP-1.md").write_text("# CSA for CP-1", encoding="utf-8")
    (csa_dir / "CP-2.md").write_text("# CSA for CP-2", encoding="utf-8")
    (tmp_path / "policy").mkdir()
    (tmp_path / "policy" / "margin_policy.md").write_text("# Margin policy", encoding="utf-8")
    (tmp_path / "README.txt").write_text("not a document", encoding="utf-8")
    return tmp_path


class TestUploadCorpus:
    @mock_aws
    def test_uploads_every_markdown_file_preserving_relative_path(self, corpus_dir) -> None:
        boto3.client("s3", region_name="ap-south-1").create_bucket(
            Bucket="test-documents-bucket",
            CreateBucketConfiguration={"LocationConstraint": "ap-south-1"},
        )
        settings = Settings(
            _env_file=None,
            s3_documents_bucket="test-documents-bucket",
            s3_documents_bucket_owner="123456789012",
        )

        uploaded_keys = upload_corpus(corpus_dir, settings=settings)

        assert sorted(uploaded_keys) == [
            "csa/CP-1.md",
            "csa/CP-2.md",
            "policy/margin_policy.md",
        ]

        s3 = boto3.client("s3", region_name="ap-south-1")
        body = s3.get_object(Bucket="test-documents-bucket", Key="csa/CP-1.md")["Body"].read()
        assert body == b"# CSA for CP-1"

    def test_missing_bucket_config_raises(self, corpus_dir) -> None:
        settings = Settings(_env_file=None, s3_documents_bucket=None)

        with pytest.raises(ValueError, match="S3_DOCUMENTS_BUCKET"):
            upload_corpus(corpus_dir, settings=settings)

    def test_missing_bucket_owner_config_raises(self, corpus_dir) -> None:
        settings = Settings(
            _env_file=None,
            s3_documents_bucket="test-documents-bucket",
            s3_documents_bucket_owner=None,
        )

        with pytest.raises(ValueError, match="S3_DOCUMENTS_BUCKET_OWNER"):
            upload_corpus(corpus_dir, settings=settings)

    # No moto-based test for a mismatched ExpectedBucketOwner: moto does not
    # enforce this check (a wrong owner silently succeeds against the mock),
    # so such a test would only assert moto's behavior, not this code's.
    # Verified manually against the real bucket instead -- a mismatched owner
    # correctly raises AccessDenied (see docs/PROGRESS.md).


class TestIterCorpusDocuments:
    @mock_aws
    def test_returns_every_markdown_document_as_key_text_pairs(self, corpus_dir) -> None:
        boto3.client("s3", region_name="ap-south-1").create_bucket(
            Bucket="test-documents-bucket",
            CreateBucketConfiguration={"LocationConstraint": "ap-south-1"},
        )
        settings = Settings(
            _env_file=None,
            s3_documents_bucket="test-documents-bucket",
            s3_documents_bucket_owner="123456789012",
        )
        upload_corpus(corpus_dir, settings=settings)

        documents = iter_corpus_documents(settings=settings)

        assert dict(documents) == {
            "csa/CP-1.md": "# CSA for CP-1",
            "csa/CP-2.md": "# CSA for CP-2",
            "policy/margin_policy.md": "# Margin policy",
        }

    @mock_aws
    def test_skips_non_markdown_objects_in_the_bucket(self) -> None:
        s3 = boto3.client("s3", region_name="ap-south-1")
        s3.create_bucket(
            Bucket="test-documents-bucket",
            CreateBucketConfiguration={"LocationConstraint": "ap-south-1"},
        )
        s3.put_object(Bucket="test-documents-bucket", Key="csa/CP-1.md", Body=b"# CSA for CP-1")
        s3.put_object(Bucket="test-documents-bucket", Key="README.txt", Body=b"not a document")
        settings = Settings(
            _env_file=None,
            s3_documents_bucket="test-documents-bucket",
            s3_documents_bucket_owner="123456789012",
        )

        documents = iter_corpus_documents(settings=settings)

        assert dict(documents) == {"csa/CP-1.md": "# CSA for CP-1"}

    def test_missing_bucket_config_raises(self) -> None:
        settings = Settings(_env_file=None, s3_documents_bucket=None)

        with pytest.raises(ValueError, match="S3_DOCUMENTS_BUCKET"):
            iter_corpus_documents(settings=settings)

    def test_missing_bucket_owner_config_raises(self) -> None:
        settings = Settings(
            _env_file=None,
            s3_documents_bucket="test-documents-bucket",
            s3_documents_bucket_owner=None,
        )

        with pytest.raises(ValueError, match="S3_DOCUMENTS_BUCKET_OWNER"):
            iter_corpus_documents(settings=settings)
