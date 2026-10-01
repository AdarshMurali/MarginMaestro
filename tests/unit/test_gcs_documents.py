"""MM-111: RAG documents in Google Cloud Storage + the DOCUMENT_STORE switch."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from config.settings import Settings
from rag import documents, gcs_documents


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, gcs_documents_bucket="mm-docs", **overrides)


def _client_with(blobs: dict[str, str]) -> tuple[MagicMock, MagicMock]:
    client = MagicMock()
    bucket = client.bucket.return_value
    bucket.list_blobs.return_value = [
        SimpleNamespace(name=name, download_as_text=lambda encoding, text=text: text)
        for name, text in blobs.items()
    ]
    return client, bucket


def test_upload_keeps_relative_paths_as_object_names(tmp_path: Path):
    (tmp_path / "csa").mkdir()
    (tmp_path / "csa" / "CP-3.md").write_text("# CP-3 CSA", encoding="utf-8")
    (tmp_path / "policy").mkdir()
    (tmp_path / "policy" / "margin_policy.md").write_text("# Policy", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("ignored", encoding="utf-8")
    client, bucket = _client_with({})

    names = gcs_documents.upload_corpus(tmp_path, settings=_settings(), client=client)

    assert names == ["csa/CP-3.md", "policy/margin_policy.md"]
    client.bucket.assert_called_with("mm-docs")
    assert [c.args[0] for c in bucket.blob.call_args_list] == names
    bucket.blob.return_value.upload_from_filename.assert_called_with(
        str(tmp_path / "policy" / "margin_policy.md"), content_type="text/markdown"
    )


def test_iter_returns_markdown_only_sorted_by_name():
    client, _ = _client_with(
        {"policy/margin_policy.md": "policy", "csa/CP-3.md": "cp3", "README.txt": "skip"}
    )

    docs = gcs_documents.iter_corpus_documents(settings=_settings(), client=client)

    assert docs == [("csa/CP-3.md", "cp3"), ("policy/margin_policy.md", "policy")]


def test_missing_bucket_fails_loud():
    with pytest.raises(ValueError, match="GCS_DOCUMENTS_BUCKET"):
        gcs_documents.iter_corpus_documents(settings=Settings(_env_file=None), client=MagicMock())


def test_default_client_is_a_storage_client_for_the_project():
    with patch("google.cloud.storage.Client") as client_cls:
        gcs_documents.iter_corpus_documents(settings=_settings(gcp_project_id="proj-x"))

    client_cls.assert_called_once_with(project="proj-x")


def test_cli_uploads_the_given_folder(tmp_path: Path, capsys):
    with (
        patch.object(gcs_documents, "upload_corpus", return_value=["a.md", "b.md"]) as upload,
        patch.object(gcs_documents, "get_settings", return_value=_settings()),
    ):
        gcs_documents.main([str(tmp_path)])

    upload.assert_called_once_with(tmp_path)
    assert "Uploaded 2 documents to gs://mm-docs/" in capsys.readouterr().out


# --- DOCUMENT_STORE switch ------------------------------------------------------


def test_default_document_store_is_s3_so_aws_is_unchanged():
    with patch("rag.s3_upload.iter_corpus_documents", return_value=[("k", "v")]) as s3:
        assert documents.iter_corpus_documents(Settings(_env_file=None)) == [("k", "v")]
    s3.assert_called_once()


def test_gcs_document_store():
    with patch("rag.gcs_documents.iter_corpus_documents", return_value=[("g", "v")]) as gcs:
        assert documents.iter_corpus_documents(_settings(document_store=" GCS ")) == [("g", "v")]
    gcs.assert_called_once()


def test_unknown_document_store_fails_loud():
    with pytest.raises(ValueError, match="DOCUMENT_STORE"):
        documents.iter_corpus_documents(_settings(document_store="dropbox"))
