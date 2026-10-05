"""MM-137: summary of the Sensitive Data Protection scan of the documents
bucket -- counts per info type, never the values."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from config.settings import Settings
from governance import sdp_scan


def _job(findings: dict[str, int]) -> SimpleNamespace:
    stats = [
        SimpleNamespace(info_type=SimpleNamespace(name=name), count=count)
        for name, count in findings.items()
    ]
    return SimpleNamespace(
        name="projects/p/locations/us-central1/dlpJobs/i-1",
        state=SimpleNamespace(name="DONE"),
        inspect_details=SimpleNamespace(
            result=SimpleNamespace(processed_bytes=42_000, info_type_stats=stats)
        ),
    )


def test_summary_of_the_newest_job_of_the_trigger():
    client = MagicMock()
    client.list_dlp_jobs.return_value = [_job({"EMAIL_ADDRESS": 2, "PERSON_NAME": 8}), _job({})]

    summary = sdp_scan.latest_scan_summary(client, "p", "us-central1")

    assert summary == {
        "job": "projects/p/locations/us-central1/dlpJobs/i-1",
        "state": "DONE",
        "processed_bytes": 42_000,
        "findings": {"EMAIL_ADDRESS": 2, "PERSON_NAME": 8},
        "total_findings": 10,
    }
    request = client.list_dlp_jobs.call_args.kwargs["request"]
    assert request["parent"] == "projects/p/locations/us-central1"
    assert request["filter"] == (
        "trigger_name = projects/p/locations/us-central1/jobTriggers/marginmaestro-documents-scan"
    )
    assert request["order_by"] == "create_time desc"


def test_no_job_yet_is_none():
    client = MagicMock()
    client.list_dlp_jobs.return_value = []
    assert sdp_scan.latest_scan_summary(client, "p", "l") is None


@pytest.fixture
def gcp_settings():
    settings = Settings(_env_file=None, gcp_project_id="p")
    with patch("governance.sdp_scan.get_settings", return_value=settings):
        yield


def test_main_logs_findings_at_warning_and_prints_json(gcp_settings, capsys):
    client = MagicMock()
    client.list_dlp_jobs.return_value = [_job({"EMAIL_ADDRESS": 1})]
    with (
        patch("google.cloud.dlp_v2.DlpServiceClient", return_value=client),
        patch("governance.sdp_scan.logger") as logger,
    ):
        sdp_scan.main()

    assert logger.warning.call_args.args[0] == "sdp_scan_summary"
    assert json.loads(capsys.readouterr().out)["total_findings"] == 1


def test_main_reports_a_clean_scan_at_info(gcp_settings):
    client = MagicMock()
    client.list_dlp_jobs.return_value = [_job({})]
    with (
        patch("google.cloud.dlp_v2.DlpServiceClient", return_value=client),
        patch("governance.sdp_scan.logger") as logger,
    ):
        sdp_scan.main()

    logger.info.assert_called_once()


def test_main_when_never_run(gcp_settings, capsys):
    client = MagicMock()
    client.list_dlp_jobs.return_value = []
    with patch("google.cloud.dlp_v2.DlpServiceClient", return_value=client):
        sdp_scan.main()
    assert "No scan has run yet" in capsys.readouterr().out


def test_main_needs_a_project():
    with (
        patch("governance.sdp_scan.get_settings", return_value=Settings(_env_file=None)),
        pytest.raises(SystemExit, match="GCP_PROJECT_ID"),
    ):
        sdp_scan.main()
