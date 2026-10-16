"""MM-147 follow-up: how a queued 'Ask the Desk' turn actually runs --
SyncDeskJobDispatcher (inline), CloudTasksDeskJobDispatcher (one task per
turn), and the factory that picks between them."""

import re
from unittest.mock import MagicMock, patch

import pytest
from google.api_core.exceptions import AlreadyExists, ServiceUnavailable

from adapters import factory
from adapters.desk_job_dispatcher import (
    CloudTasksDeskJobDispatcher,
    SyncDeskJobDispatcher,
    task_id_for,
)
from config.settings import Settings

QUEUE = "projects/p/locations/us-central1/queues/sla-checks"
INVOKER = "mm-invoker-sa@p.iam.gserviceaccount.com"
JOB_ID = "f6a1c2d3-0000-4000-8000-000000000001"


def _dispatcher(client):
    return CloudTasksDeskJobDispatcher(
        QUEUE, "https://api.example.run.app/", INVOKER, "aud", client
    )


# --- SyncDeskJobDispatcher -------------------------------------------------------


def test_sync_dispatch_runs_the_job_inline():
    run_job = MagicMock()

    SyncDeskJobDispatcher(run_job).dispatch(JOB_ID)

    run_job.assert_called_once_with(JOB_ID)


# --- CloudTasksDeskJobDispatcher --------------------------------------------------


def test_task_id_is_valid_stable_and_per_job():
    task_id = task_id_for(JOB_ID)

    assert re.fullmatch(r"[A-Za-z0-9_-]{1,500}", task_id)
    assert task_id == task_id_for(JOB_ID)
    assert task_id != task_id_for("some-other-job")


def test_creates_one_http_task_with_an_oidc_token():
    client = MagicMock()

    _dispatcher(client).dispatch(JOB_ID)

    request = client.create_task.call_args.kwargs["request"]
    task = request["task"]
    assert request["parent"] == QUEUE
    assert task["name"] == f"{QUEUE}/tasks/{task_id_for(JOB_ID)}"
    http = task["http_request"]
    assert http["http_method"] == "POST"
    assert http["url"] == f"https://api.example.run.app/internal/desk/run-job/{JOB_ID}"
    assert http["oidc_token"] == {"service_account_email": INVOKER, "audience": "aud"}


def test_dispatching_the_same_job_twice_is_a_no_op():
    client = MagicMock()
    client.create_task.side_effect = [None, AlreadyExists("task exists")]
    dispatcher = _dispatcher(client)

    dispatcher.dispatch(JOB_ID)
    dispatcher.dispatch(JOB_ID)  # no error

    assert client.create_task.call_count == 2


def test_other_cloud_tasks_errors_propagate():
    client = MagicMock()
    client.create_task.side_effect = ServiceUnavailable("down")

    with pytest.raises(ServiceUnavailable):
        _dispatcher(client).dispatch(JOB_ID)


# --- factory -----------------------------------------------------------------------


def test_factory_defaults_to_sync():
    run_job = MagicMock()

    dispatcher = factory.get_desk_job_dispatcher(Settings(_env_file=None), run_job)

    assert isinstance(dispatcher, SyncDeskJobDispatcher)
    dispatcher.dispatch(JOB_ID)
    run_job.assert_called_once_with(JOB_ID)


def test_factory_cloudtasks_names_every_missing_setting():
    with pytest.raises(ValueError, match="GCP_PROJECT_ID, INTERNAL_BASE_URL"):
        factory.get_desk_job_dispatcher(
            Settings(_env_file=None, desk_job_dispatch="cloudtasks"), MagicMock()
        )


def test_factory_builds_cloud_tasks_for_the_queue():
    settings = Settings(
        _env_file=None,
        desk_job_dispatch="cloudtasks",
        gcp_project_id="p",
        internal_base_url="https://api.example.run.app",
        internal_caller_service_account=INVOKER,
        internal_caller_audience="aud",
    )
    with patch("adapters.desk_job_dispatcher._tasks_client") as client:
        dispatcher = factory.get_desk_job_dispatcher(settings, MagicMock())

    assert isinstance(dispatcher, CloudTasksDeskJobDispatcher)
    dispatcher.dispatch(JOB_ID)
    assert client.return_value.create_task.call_args.kwargs["request"]["parent"] == QUEUE


def test_unknown_dispatch_mode_fails_loud():
    with pytest.raises(ValueError, match="DESK_JOB_DISPATCH"):
        factory.get_desk_job_dispatcher(
            Settings(_env_file=None, desk_job_dispatch="cron"), MagicMock()
        )
