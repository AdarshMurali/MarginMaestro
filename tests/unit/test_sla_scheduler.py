"""MM-122: SLA timers -- the Cloud Tasks adapter, its wiring into the
orchestrator (armed once, right after the notice is sent), and the
`/internal/sla/{thread_id}/check` endpoint the timer calls."""

import re
from datetime import UTC, date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from google.api_core.exceptions import AlreadyExists, ServiceUnavailable
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from adapters import factory
from adapters.cloud_tasks_sla import CloudTasksSlaScheduler, NoSlaScheduler, task_id_for
from agents.communication import NotificationResult
from agents.escalation import IncidentResult
from agents.orchestrator import (
    MarginCallState,
    build_orchestrator_graph,
    resume_run,
    start_run,
    thread_id_for,
)
from api.main import app
from config.settings import Settings
from persistence.audit import list_audit_events
from persistence.db.models import (
    Base,
    CollateralItemORM,
    CounterpartyORM,
    PortfolioORM,
    PositionORM,
    PriceHistoryORM,
    ReferenceRateORM,
)
from rag.models import CSATermsResult
from streaming.market_feed import PriceQuote
from streaming.schemas import ImpactSet, MarketEventType

QUEUE = "projects/p/locations/us-central1/queues/sla-checks"
INVOKER = "mm-invoker-sa@p.iam.gserviceaccount.com"
THREAD = "TSLA:2026-10-02T15:00:00+00:00:yfinance:CP-1"
DEADLINE = datetime(2026, 10, 2, 16, 0, tzinfo=UTC)

# --- adapter -------------------------------------------------------------------


def _scheduler(client):
    return CloudTasksSlaScheduler(QUEUE, "https://api.example.run.app/", INVOKER, "aud", client)


def test_task_id_is_valid_stable_and_per_thread():
    task_id = task_id_for(THREAD)

    assert re.fullmatch(r"[A-Za-z0-9_-]{1,500}", task_id)
    assert task_id == task_id_for(THREAD)
    assert task_id != task_id_for(THREAD.replace("CP-1", "CP-2"))


def test_creates_one_http_task_at_the_deadline_with_an_oidc_token():
    client = MagicMock()

    _scheduler(client).schedule_check(THREAD, DEADLINE)

    request = client.create_task.call_args.kwargs["request"]
    task = request["task"]
    assert request["parent"] == QUEUE
    assert task["name"] == f"{QUEUE}/tasks/{task_id_for(THREAD)}"
    assert task["schedule_time"] == DEADLINE
    http = task["http_request"]
    assert http["http_method"] == "POST"
    assert http["url"] == (
        "https://api.example.run.app/internal/sla/"
        "TSLA%3A2026-10-02T15%3A00%3A00%2B00%3A00%3Ayfinance%3ACP-1/check"
    )
    assert http["oidc_token"] == {"service_account_email": INVOKER, "audience": "aud"}


def test_scheduling_the_same_call_twice_is_a_no_op():
    client = MagicMock()
    client.create_task.side_effect = [None, AlreadyExists("task exists")]
    scheduler = _scheduler(client)

    scheduler.schedule_check(THREAD, DEADLINE)
    scheduler.schedule_check(THREAD, DEADLINE)  # no error

    assert client.create_task.call_count == 2


def test_other_cloud_tasks_errors_propagate():
    client = MagicMock()
    client.create_task.side_effect = ServiceUnavailable("down")

    with pytest.raises(ServiceUnavailable):
        _scheduler(client).schedule_check(THREAD, DEADLINE)


def test_no_scheduler_does_nothing():
    NoSlaScheduler().schedule_check(THREAD, DEADLINE)


def test_factory_defaults_to_no_timer():
    assert isinstance(factory.get_sla_scheduler(Settings(_env_file=None)), NoSlaScheduler)


def test_factory_cloudtasks_names_every_missing_setting():
    with pytest.raises(ValueError, match="GCP_PROJECT_ID, INTERNAL_BASE_URL"):
        factory.get_sla_scheduler(Settings(_env_file=None, sla_scheduler="cloudtasks"))


def test_factory_builds_cloud_tasks_for_the_queue():
    settings = Settings(
        _env_file=None,
        sla_scheduler="cloudtasks",
        gcp_project_id="p",
        internal_base_url="https://api.example.run.app",
        internal_caller_service_account=INVOKER,
        internal_caller_audience="aud",
    )
    with patch("adapters.cloud_tasks_sla._tasks_client") as client:
        scheduler = factory.get_sla_scheduler(settings)

    assert isinstance(scheduler, CloudTasksSlaScheduler)
    scheduler.schedule_check(THREAD, DEADLINE)
    assert client.return_value.create_task.call_args.kwargs["request"]["parent"] == QUEUE


def test_unknown_scheduler_fails_loud():
    with pytest.raises(ValueError, match="SLA_SCHEDULER"):
        factory.get_sla_scheduler(Settings(_env_file=None, sla_scheduler="cron"))


# --- orchestrator wiring -----------------------------------------------------------


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory_ = sessionmaker(bind=engine)
    with factory_() as session:
        session.add(CounterpartyORM(id="CP-1", name="CP-1", type="Bank", country="US"))
        session.add(PortfolioORM(id="PF-CP-1", counterparty_id="CP-1", currency="USD"))
        session.add(
            PositionORM(
                id="POS-1",
                portfolio_id="PF-CP-1",
                ticker="TSLA",
                asset_class="equity",
                quantity=1000,
                trade_date=date(2026, 1, 1),
            )
        )
        session.add(
            PriceHistoryORM(
                ticker="TSLA",
                price_date=date(2026, 7, 30),
                price=100.0,
                currency="USD",
                source="yfinance",
            )
        )
        session.add(ReferenceRateORM(series_id="VIXCLS", rate_date=date(2026, 7, 30), value=20.0))
        session.add(
            CollateralItemORM(
                id="C1",
                counterparty_id="CP-1",
                collateral_type="cash",
                value_usd=0.0,
                haircut_pct=0.0,
            )
        )
        session.commit()
    return factory_


def _state() -> MarginCallState:
    impact = ImpactSet(
        event_id="evt-1",
        event_type=MarketEventType.PRICE_SHOCK,
        counterparty_ids=["CP-1"],
        reason="TSLA moved 400.0% vs prior close",
        occurred_at=datetime.now(UTC),
    )
    return MarginCallState(correlation_id="corr-1", impact=impact, counterparty_id="CP-1")


def _graph(session_factory, settings, scheduler):
    feed = MagicMock()
    feed.get_prices.return_value = {
        "TSLA": PriceQuote(ticker="TSLA", price=500.0, as_of=datetime.now(UTC), source="yfinance")
    }
    return build_orchestrator_graph(
        session_factory=session_factory,
        market_feed=feed,
        settings=settings,
        sla_scheduler=scheduler,
    )


CSA = CSATermsResult(
    counterparty_id="CP-1",
    threshold=1_000.0,
    mta=10_000.0,
    currency="USD",
    eligible_collateral=["cash"],
    haircuts={"cash": 0.0},
    rating_triggers=[],
    citations=[],
)
SENT = NotificationResult(notice_text="notice", slack_channel="C1", slack_ts="1.2")


def _patched_agents():
    return (
        patch("agents.orchestrator.answer_csa_terms", return_value=CSA),
        patch("agents.orchestrator.draft_margin_call_notice", return_value="notice"),
        patch("agents.orchestrator.send_slack_notice", return_value=SENT),
    )


def _run_to_sla_pause(session_factory, settings, scheduler):
    """Start a breached run and approve it, so it's paused at the SLA step."""
    graph = _graph(session_factory, settings, scheduler)
    state = _state()
    thread_id = thread_id_for(state.impact, state.counterparty_id)
    csa, draft, send = _patched_agents()
    with csa, draft, send:
        start_run(graph, state)
        scheduler.schedule_check.assert_not_called()  # nothing sent yet: no timer
        resume_run(graph, thread_id, {"decision": "approved", "approver_username": "alice"})
    return graph, thread_id


def test_the_timer_is_armed_once_at_the_deadline_after_the_notice(session_factory):
    scheduler = MagicMock()
    settings = Settings(_env_file=None, margin_call_sla_minutes=60)

    graph, thread_id = _run_to_sla_pause(session_factory, settings, scheduler)

    scheduler.schedule_check.assert_called_once()
    scheduled_thread, at = scheduler.schedule_check.call_args.args
    sent_at = graph.get_state({"configurable": {"thread_id": thread_id}}).values[
        "notification_sent_at"
    ]
    assert scheduled_thread == thread_id
    assert at == sent_at + timedelta(minutes=60)


def test_a_rejected_call_arms_no_timer(session_factory):
    scheduler = MagicMock()
    graph = _graph(session_factory, Settings(_env_file=None), scheduler)
    state = _state()
    csa, draft, send = _patched_agents()
    with csa, draft, send:
        start_run(graph, state)
        resume_run(
            graph,
            thread_id_for(state.impact, state.counterparty_id),
            {"decision": "rejected", "approver_username": "alice"},
        )

    scheduler.schedule_check.assert_not_called()


def test_a_scheduling_failure_never_fails_the_sent_notice(session_factory):
    """The notice is out: failing the node would re-send it on retry. The run
    still reaches the SLA step, and the audit trail records the failure."""
    scheduler = MagicMock()
    scheduler.schedule_check.side_effect = ServiceUnavailable("cloud tasks down")

    graph, thread_id = _run_to_sla_pause(
        session_factory, Settings(_env_file=None, margin_call_sla_minutes=60), scheduler
    )

    snapshot = graph.get_state({"configurable": {"thread_id": thread_id}})
    assert {t.name for t in snapshot.tasks if t.interrupts} == {"await_sla_response"}
    with session_factory() as session:
        events = [e.event_type for e in list_audit_events(session, "corr-1", "CP-1")]
    assert "sla_check_schedule_failed" in events
    assert events.index("sla_check_schedule_failed") > events.index("send_notification")


# --- /internal/sla/{thread_id}/check --------------------------------------------------


def _check(graph, thread_id, token="t"):
    settings = Settings(_env_file=None, internal_job_token="t")
    with (
        patch("api.auth.get_settings", return_value=settings),
        patch("api.main.get_orchestrator_graph", return_value=graph),
        patch("agents.orchestrator.retrieve_escalation_procedure", return_value="procedure"),
        patch(
            "agents.orchestrator.open_servicenow_incident",
            return_value=IncidentResult(incident_number="INC0010001", sys_id="abc", urgency="2"),
        ) as incident,
    ):
        response = TestClient(app).post(
            f"/internal/sla/{thread_id}/check", headers={"Authorization": f"Bearer {token}"}
        )
    return response, incident


def test_check_before_the_deadline_asks_cloud_tasks_to_retry(session_factory):
    graph, thread_id = _run_to_sla_pause(
        session_factory, Settings(_env_file=None, margin_call_sla_minutes=60), MagicMock()
    )

    response, incident = _check(graph, thread_id)

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "30"
    incident.assert_not_called()


def test_check_after_the_deadline_breaches_and_escalates(session_factory):
    graph, thread_id = _run_to_sla_pause(
        session_factory, Settings(_env_file=None, margin_call_sla_minutes=0), MagicMock()
    )

    response, incident = _check(graph, thread_id)

    assert response.status_code == 200
    assert response.json() == {"thread_id": thread_id, "sla_outcome": "breached"}
    incident.assert_called_once()

    again, incident = _check(graph, thread_id)  # a retried task: already resolved
    assert again.json()["sla_outcome"] == "breached"
    incident.assert_not_called()


def test_check_after_the_client_responded_is_a_no_op(session_factory):
    graph, thread_id = _run_to_sla_pause(
        session_factory, Settings(_env_file=None, margin_call_sla_minutes=60), MagicMock()
    )
    with (
        patch("agents.orchestrator.draft_sla_met_notice", return_value="thanks"),
        patch("agents.orchestrator.send_slack_notice", return_value=SENT),
    ):
        resume_run(graph, thread_id, {"responded": True})

    response, incident = _check(graph, thread_id)

    assert response.json() == {"thread_id": thread_id, "sla_outcome": "met"}
    incident.assert_not_called()


def test_check_on_a_call_still_awaiting_approval_is_a_409(session_factory):
    graph = _graph(session_factory, Settings(_env_file=None), MagicMock())
    state = _state()
    csa, draft, send = _patched_agents()
    with csa, draft, send:
        start_run(graph, state)

    response, _ = _check(graph, thread_id_for(state.impact, state.counterparty_id))

    assert response.status_code == 409


def test_check_on_an_unknown_call_is_a_404(session_factory):
    graph = _graph(session_factory, Settings(_env_file=None), MagicMock())

    response, _ = _check(graph, "nope:CP-1")

    assert response.status_code == 404


def test_check_needs_the_internal_caller(session_factory):
    graph = _graph(session_factory, Settings(_env_file=None), MagicMock())

    response, _ = _check(graph, "nope:CP-1", token="wrong")

    assert response.status_code == 401
