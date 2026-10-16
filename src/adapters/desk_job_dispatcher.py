"""Desk-chat job dispatch (MM-147 follow-up, ADR-0019 follow-up): how a
queued "Ask the Desk" turn actually gets run. POST /desk/chat always
returns as soon as the job is dispatched -- the question is just whether
that happens before or after the Agent Runtime call completes.

DESK_JOB_DISPATCH=sync (default, local dev): runs the job inline, so
dispatch() itself blocks for the full Agent Runtime call -- no new
infrastructure, and tests need nothing extra, but a slow cold call is still
slow end to end.

DESK_JOB_DISPATCH=cloudtasks (GCP): queues one Cloud Task per turn, hitting
{internal_base_url}/internal/desk/run-job/{job_id} as the invoker SA.
dispatch() returns as soon as the task is queued -- milliseconds, regardless
of how long Agent Runtime takes -- which is the actual fix: the slow call
never sits on the HTTP path to the browser, so Firebase Hosting's edge
timeout (found live: ~60s, well under Agent Runtime's observed 90+s cold
start) can't cut it off before the frontend sees the final answer.
"""

import hashlib
from collections.abc import Callable
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class SyncDeskJobDispatcher:
    """Runs the job inline before dispatch() returns."""

    def __init__(self, run_job: Callable[[str], None]) -> None:
        self._run_job = run_job

    def dispatch(self, job_id: str) -> None:
        self._run_job(job_id)


def task_id_for(job_id: str) -> str:
    """Cloud Tasks ids allow only [A-Za-z0-9_-]; job_id is already a plain
    UUID, but hash it anyway so a task name is never a raw secret-looking
    id in Cloud Tasks' own console/logs, matching cloud_tasks_sla.py."""
    return "desk-" + hashlib.sha256(job_id.encode("utf-8")).hexdigest()[:40]


class CloudTasksDeskJobDispatcher:
    def __init__(
        self,
        queue_path: str,
        base_url: str,
        invoker_service_account: str,
        audience: str,
        client: Any | None = None,
    ) -> None:
        self._queue_path = queue_path
        self._base_url = base_url.rstrip("/")
        self._invoker = invoker_service_account
        self._audience = audience
        self._client = client if client is not None else _tasks_client()

    def dispatch(self, job_id: str) -> None:
        from google.api_core.exceptions import AlreadyExists

        task = {
            "name": f"{self._queue_path}/tasks/{task_id_for(job_id)}",
            "http_request": {
                "http_method": "POST",
                "url": f"{self._base_url}/internal/desk/run-job/{job_id}",
                "oidc_token": {
                    "service_account_email": self._invoker,
                    "audience": self._audience,
                },
            },
        }
        try:
            self._client.create_task(request={"parent": self._queue_path, "task": task})
        except AlreadyExists:
            logger.info("desk_job_already_dispatched", job_id=job_id)
            return
        logger.info("desk_job_dispatched", job_id=job_id)


def _tasks_client() -> Any:
    from google.cloud.tasks_v2 import CloudTasksClient

    return CloudTasksClient()
