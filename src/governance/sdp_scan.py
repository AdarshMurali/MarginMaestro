"""Summary of the latest Sensitive Data Protection scan of the documents
bucket (MM-137). The job trigger itself is Terraform
(infra/gcp/governance.tf, `marginmaestro-documents-scan`); this reads its
newest job and logs one structured `sdp_scan_summary` event (Cloud Logging
when run on GCP) -- counts per info type, never the matched values.

    python -m governance.sdp_scan          # needs GCP_PROJECT_ID and ADC
"""

import json
from typing import Any

import structlog

from config.settings import get_settings

TRIGGER_ID = "marginmaestro-documents-scan"
logger = structlog.get_logger(__name__)


def latest_scan_summary(
    client: Any, project_id: str, location: str, trigger_id: str = TRIGGER_ID
) -> dict[str, Any] | None:
    """The newest inspection job of the trigger, summarised; None if it has
    never run."""
    parent = f"projects/{project_id}/locations/{location}"
    jobs = client.list_dlp_jobs(
        request={
            "parent": parent,
            "filter": f"trigger_name = {parent}/jobTriggers/{trigger_id}",
            "type_": "INSPECT_JOB",
            "order_by": "create_time desc",
        }
    )
    job = next(iter(jobs), None)
    if job is None:
        return None
    result = job.inspect_details.result
    findings = {stat.info_type.name: int(stat.count) for stat in result.info_type_stats}
    return {
        "job": job.name,
        "state": getattr(job.state, "name", str(job.state)),
        "processed_bytes": int(result.processed_bytes),
        "findings": findings,
        "total_findings": sum(findings.values()),
    }


def main() -> None:
    settings = get_settings()
    if not settings.gcp_project_id:
        raise SystemExit("GCP_PROJECT_ID is required")
    from google.cloud.dlp_v2 import DlpServiceClient

    summary = latest_scan_summary(
        DlpServiceClient(), settings.gcp_project_id, settings.sdp_location
    )
    if summary is None:
        logger.warning("sdp_scan_summary", status="never_run", trigger=TRIGGER_ID)
        print(f"No scan has run yet for {TRIGGER_ID}.")
        return
    log = logger.warning if summary["total_findings"] else logger.info
    log("sdp_scan_summary", **summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
