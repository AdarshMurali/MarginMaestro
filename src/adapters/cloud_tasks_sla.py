"""SLA timers on Cloud Tasks (MM-122, ADR-0012): one task per margin call,
scheduled for the call's exact SLA deadline, that calls
`POST {internal_base_url}/internal/sla/{thread_id}/check` with a Google-signed
OIDC token for the invoker service account. Replaces "a human or a cron calls
/check-sla" with a timer that fires on time without polling.

- Idempotent: the task name is derived from the thread id, so scheduling the
  same call twice is rejected by Cloud Tasks (AlreadyExists) and ignored.
- Retries (queue config, infra/gcp/cloud_tasks.tf) cover an API that's down or
  a check that ran a moment early.

`SLA_SCHEDULER=none` (default) keeps today's behaviour: no timer, the check is
called by hand.
"""

import hashlib
import json
from datetime import datetime
from typing import Any
from urllib.parse import quote

import structlog

logger = structlog.get_logger(__name__)


class NoSlaScheduler:
    """Default: no timer. The SLA check runs only when someone calls it."""

    def schedule_check(self, thread_id: str, at: datetime) -> None:
        logger.info("sla_check_not_scheduled", thread_id=thread_id, deadline=at.isoformat())


def task_id_for(thread_id: str) -> str:
    """Cloud Tasks ids allow only [A-Za-z0-9_-]; thread ids contain ':' and '+'.
    A hash keeps the id valid, fixed-length and stable for the same thread."""
    return "sla-" + hashlib.sha256(thread_id.encode("utf-8")).hexdigest()[:40]


class CloudTasksSlaScheduler:
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

    def schedule_check(self, thread_id: str, at: datetime) -> None:
        from google.api_core.exceptions import AlreadyExists

        task = {
            "name": f"{self._queue_path}/tasks/{task_id_for(thread_id)}",
            "schedule_time": at,  # proto-plus converts datetime to Timestamp
            "http_request": {
                "http_method": "POST",
                "url": f"{self._base_url}/internal/sla/{quote(thread_id, safe='')}/check",
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"thread_id": thread_id}).encode("utf-8"),
                "oidc_token": {
                    "service_account_email": self._invoker,
                    "audience": self._audience,
                },
            },
        }
        try:
            self._client.create_task(request={"parent": self._queue_path, "task": task})
        except AlreadyExists:
            logger.info("sla_check_already_scheduled", thread_id=thread_id)
            return
        logger.info("sla_check_scheduled", thread_id=thread_id, deadline=at.isoformat())


def _tasks_client() -> Any:
    from google.cloud.tasks_v2 import CloudTasksClient

    return CloudTasksClient()
