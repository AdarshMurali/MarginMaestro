"""MM-146: the Firestore status publisher -- one doc per call, rewritten on
every lifecycle change (real orchestrator graph on SQLite, fake Firestore),
copied from the feed's own summary, best effort and idempotent."""

import sys
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from agents.communication import NotificationResult
from agents.escalation import IncidentResult
from agents.orchestrator import (
    MarginCallState,
    build_orchestrator_graph,
    reevaluate_run,
    resume_run,
    start_run,
    thread_id_for,
)
from api.margin_calls import summarize_run
from calc.models import BreachResult
from config.settings import Settings
from persistence.db.models import (
    Base,
    CollateralItemORM,
    CounterpartyORM,
    PortfolioORM,
    PositionORM,
    PriceHistoryORM,
    ReferenceRateORM,
)
from persistence.models import CounterpartyTier
from rag.models import CSATermsResult
from realtime.publisher import (
    CallStatusDoc,
    FirestoreStatusPublisher,
    NoStatusPublisher,
    build_status_publisher,
    doc_id,
    status_doc,
)
from streaming.market_feed import PriceQuote
from streaming.schemas import ImpactSet, MarketEventType

COLLECTION = "margin_call_status"


class FakeFirestore:
    """Records collection(...).document(...).set(...) calls."""

    def __init__(self) -> None:
        self.writes: list[tuple[str, str, dict]] = []
        self.fail = False

    def collection(self, name: str):
        def document(doc: str):
            def set_(data: dict) -> None:
                if self.fail:
                    raise RuntimeError("firestore unavailable")
                self.writes.append((name, doc, data))

            return SimpleNamespace(set=set_)

        return SimpleNamespace(document=document)

    @property
    def statuses(self) -> list[str]:
        return [data["status"] for _, _, data in self.writes]


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def _publisher(client: FakeFirestore, **settings) -> FirestoreStatusPublisher:
    return FirestoreStatusPublisher(client, COLLECTION, _settings(**settings))


# --- a real call through the orchestrator -------------------------------------------


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        session.add(CounterpartyORM(id="CP-1", name="Acme Capital", type="Bank", country="US"))
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
    return factory


def _state() -> MarginCallState:
    impact = ImpactSet(
        event_id="evt-1",
        event_type=MarketEventType.PRICE_SHOCK,
        counterparty_ids=["CP-1"],
        reason="TSLA moved 12.0% vs prior close",
        occurred_at=datetime.now(UTC),
    )
    return MarginCallState(correlation_id="corr-1", impact=impact, counterparty_id="CP-1")


def _market_feed() -> MagicMock:
    feed = MagicMock()
    feed.get_prices.return_value = {
        "TSLA": PriceQuote(ticker="TSLA", price=500.0, as_of=datetime.now(UTC), source="yfinance")
    }
    return feed


def _run_call(session_factory, publisher, *, sla_minutes: int, steps: list[dict]) -> str:
    csa = CSATermsResult(
        counterparty_id="CP-1",
        threshold=1_000.0,
        mta=10_000.0,
        currency="USD",
        eligible_collateral=["cash"],
        haircuts={"cash": 0.0},
        rating_triggers=[],
        citations=[],
    )
    sent = NotificationResult(
        notice_text="Mock notice.", slack_channel="C1", slack_ts="123.456", message_id="123.456"
    )
    state = _state()
    thread_id = thread_id_for(state.impact, state.counterparty_id)
    with (
        patch("agents.orchestrator.get_status_publisher", return_value=publisher),
        patch("agents.orchestrator.answer_csa_terms", return_value=csa),
        patch("agents.orchestrator.draft_margin_call_notice", return_value="Mock notice."),
        patch("agents.orchestrator.send_slack_notice", return_value=sent),
        patch("agents.orchestrator.draft_sla_met_notice", return_value="Met."),
        patch("agents.orchestrator.retrieve_escalation_procedure", return_value="Escalate."),
        patch(
            "agents.orchestrator.open_servicenow_incident",
            return_value=IncidentResult(incident_number="INC0010001", sys_id="x", urgency="2"),
        ),
    ):
        graph = build_orchestrator_graph(
            session_factory=session_factory,
            market_feed=_market_feed(),
            settings=_settings(margin_call_sla_minutes=sla_minutes),
        )
        start_run(graph, state)
        for payload in steps:
            resume_run(graph, thread_id, payload)
    return thread_id


def test_a_call_publishes_raised_notified_and_sla_met(session_factory):
    client = FakeFirestore()
    thread_id = _run_call(
        session_factory,
        _publisher(client),
        sla_minutes=60,
        steps=[{"decision": "approved", "approver_username": "alice"}, {"responded": True}],
    )

    assert client.statuses == ["awaiting_approval", "awaiting_sla_response", "sla_met"]
    assert {(name, doc) for name, doc, _ in client.writes} == {(COLLECTION, thread_id)}
    raised, notified, met = (data for _, _, data in client.writes)
    assert raised["counterparty_id"] == "CP-1"
    assert raised["thread_id"] == thread_id
    assert raised["currency"] == "USD"
    assert raised["book"] == "live"
    assert raised["sla_deadline"] is None
    assert notified["sla_deadline"] is not None
    # The call figure is copied, not recomputed: it equals the breach result's.
    assert raised["call_amount"] is not None and raised["call_amount"] > 0
    assert met["call_amount"] == raised["call_amount"]


def test_an_unanswered_call_publishes_escalated(session_factory):
    client = FakeFirestore()
    _run_call(
        session_factory,
        _publisher(client),
        sla_minutes=0,
        steps=[{"decision": "approved", "approver_username": "alice"}, {"check": True}],
    )

    assert client.statuses[-1] == "escalated"


def test_a_rejected_call_publishes_rejected(session_factory):
    client = FakeFirestore()
    _run_call(
        session_factory,
        _publisher(client),
        sla_minutes=60,
        steps=[{"decision": "rejected", "approver_username": "alice"}],
    )

    assert client.statuses == ["awaiting_approval", "rejected"]


def test_the_doc_carries_ids_and_status_only(session_factory):
    client = FakeFirestore()
    _run_call(
        session_factory,
        _publisher(client),
        sla_minutes=60,
        steps=[{"decision": "approved", "approver_username": "alice"}],
    )

    for _, _, data in client.writes:
        assert set(data) == set(CallStatusDoc.model_fields)
    text = str(client.writes)
    assert "Acme Capital" not in text  # confidential: counterparties.name
    assert "Mock notice." not in text


def test_a_firestore_outage_never_fails_the_call(session_factory):
    client = FakeFirestore()
    client.fail = True

    with patch("realtime.publisher.logger") as logger:
        thread_id = _run_call(
            session_factory,
            _publisher(client),
            sla_minutes=60,
            steps=[{"decision": "approved", "approver_username": "alice"}, {"responded": True}],
        )

    warnings = [c for c in logger.warning.call_args_list if c.args[0] == "realtime_publish_failed"]
    assert len(warnings) == 3
    assert warnings[0].kwargs["thread_id"] == thread_id


# --- entry-point hooks (mock graph) --------------------------------------------------


def _mock_graph(values: dict) -> MagicMock:
    graph = MagicMock()
    graph.invoke.return_value = {}
    graph.get_state.return_value = SimpleNamespace(values=values)
    return graph


@pytest.mark.parametrize("entry", ["start", "resume", "reevaluate"])
def test_every_entry_point_publishes_the_resting_state(entry):
    values = {"counterparty_id": "CP-1"}
    graph = _mock_graph(values)
    publisher = MagicMock(enabled=True)
    state = _state()
    thread_id = thread_id_for(state.impact, "CP-1")

    with patch("agents.orchestrator.get_status_publisher", return_value=publisher):
        if entry == "start":
            start_run(graph, state)
        elif entry == "resume":
            resume_run(graph, thread_id, {"decision": "approved"})
        else:
            reevaluate_run(graph, thread_id, state.impact, ["event-agent"])

    publisher.publish.assert_called_once_with(thread_id, values)


def test_realtime_off_never_reads_the_state_again():
    graph = _mock_graph({"counterparty_id": "CP-1"})

    with patch("agents.orchestrator.get_status_publisher", return_value=NoStatusPublisher()):
        start_run(graph, _state())

    graph.get_state.assert_not_called()


def test_a_state_read_failure_is_logged_not_raised():
    graph = _mock_graph({})
    graph.get_state.side_effect = RuntimeError("checkpointer down")
    publisher = MagicMock(enabled=True)

    with (
        patch("agents.orchestrator.get_status_publisher", return_value=publisher),
        patch("agents.orchestrator.logger") as logger,
    ):
        start_run(graph, _state())

    publisher.publish.assert_not_called()
    assert any(c.args[0] == "realtime_state_read_failed" for c in logger.warning.call_args_list)


# --- the doc itself -------------------------------------------------------------------


def _values(**overrides) -> dict:
    breach = BreachResult(breached=True, call_amount=499_000.0)
    values = {
        "correlation_id": "corr-1",
        "counterparty_id": "CP-1",
        "impact": _state().impact,
        "breach_result": breach,
        "csa_terms": None,
    }
    values.update(overrides)
    return values


@pytest.mark.parametrize(
    ("overrides", "status"),
    [
        ({}, "awaiting_approval"),
        (
            {"counterparty_tier": CounterpartyTier.ELITE, "approval_decision": "approved"},
            "awaiting_manager_approval",
        ),
        ({"approval_decision": "rejected"}, "rejected"),
        ({"approval_decision": "approved", "notification_sent_at": datetime.now(UTC)}, None),
        ({"sla_outcome": "met"}, "sla_met"),
        ({"escalation_result": object()}, "escalated"),
    ],
)
def test_status_matches_the_feed(overrides, status):
    values = _values(**overrides)
    settings = _settings()

    doc = status_doc("evt-1:CP-1", values, settings)

    expected = summarize_run("evt-1:CP-1", values, settings)
    assert doc.status == expected.status.value
    if status is not None:
        assert doc.status == status
    assert doc.call_amount == expected.call_amount
    assert doc.sla_deadline == expected.sla_deadline


def test_an_adjusted_call_publishes_the_adjusted_amount():
    doc = status_doc(
        "evt-1:CP-1",
        _values(approval_decision="adjusted", adjusted_call_amount=250_000.0),
        _settings(),
    )

    assert doc.call_amount == 250_000.0


def test_sla_deadline_uses_the_configured_sla():
    sent = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)

    doc = status_doc(
        "evt-1:CP-1",
        _values(approval_decision="approved", notification_sent_at=sent),
        _settings(margin_call_sla_minutes=45),
    )

    assert doc.status == "awaiting_sla_response"
    assert doc.sla_deadline == sent + timedelta(minutes=45)


def test_an_unchanged_status_is_not_rewritten():
    client = FakeFirestore()
    publisher = _publisher(client)

    publisher.publish("evt-1:CP-1", _values())
    publisher.publish("evt-1:CP-1", _values())
    publisher.publish("evt-1:CP-1", _values(approval_decision="rejected"))

    assert client.statuses == ["awaiting_approval", "rejected"]


def test_a_failed_write_is_retried_on_the_next_change():
    client = FakeFirestore()
    publisher = _publisher(client)
    client.fail = True
    publisher.publish("evt-1:CP-1", _values())
    client.fail = False

    publisher.publish("evt-1:CP-1", _values())

    assert client.statuses == ["awaiting_approval"]


def test_doc_ids_never_contain_a_slash():
    assert doc_id("evt/1:CP-1") == "evt_1:CP-1"
    assert doc_id("evt-1:CP-1") == "evt-1:CP-1"


# --- factory -------------------------------------------------------------------------


def test_realtime_none_is_the_default_and_disabled():
    publisher = build_status_publisher(_settings())

    assert isinstance(publisher, NoStatusPublisher)
    assert publisher.enabled is False
    publisher.publish("evt-1:CP-1", {})  # a no-op


def test_firestore_needs_a_project():
    with pytest.raises(ValueError, match="GCP_PROJECT_ID"):
        build_status_publisher(_settings(realtime="firestore"))


def test_an_unknown_value_fails_loud():
    with pytest.raises(ValueError, match="REALTIME"):
        build_status_publisher(_settings(realtime="websocket"))


def test_firestore_builds_one_client_for_the_configured_database():
    firestore_module = MagicMock()
    google_cloud = MagicMock(firestore=firestore_module)
    with patch.dict(sys.modules, {"google.cloud": google_cloud}):
        publisher = build_status_publisher(
            _settings(realtime="firestore", gcp_project_id="marginmaestro-demo")
        )

    assert isinstance(publisher, FirestoreStatusPublisher)
    firestore_module.Client.assert_called_once_with(
        project="marginmaestro-demo", database="(default)"
    )
