"""MM-136: lineage per margin call -- the OpenLineage events a full call
emits (real orchestrator graph on SQLite, mocked exporter), the Data Lineage
API exporter, and the best-effort rule (an export failure never fails a call)."""

from datetime import UTC, date, datetime
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
    resume_run,
    start_run,
    thread_id_for,
)
from config.settings import Settings
from governance.lineage import (
    CALC_INPUT_TABLES,
    JOB_NAME,
    JOB_NAMESPACE,
    DataLineageExporter,
    MarginCallLineage,
    NoLineageExporter,
    document_dataset,
    get_lineage_exporter,
    get_margin_call_lineage,
    run_id_for,
)
from persistence.db.models import (
    Base,
    CollateralItemORM,
    CounterpartyORM,
    PortfolioORM,
    PositionORM,
    PriceHistoryORM,
    ReferenceRateORM,
)
from rag.models import Citation, CSATermsResult
from streaming.market_feed import PriceQuote
from streaming.schemas import ImpactSet, MarketEventType

BUCKET = "marginmaestro-demo-documents"
CITATIONS = [
    Citation(source_file="csa/CP-1.md", section="Threshold"),
    Citation(source_file="csa/CP-1.md", section="Minimum Transfer Amount"),
]


class RecordingExporter:
    name = "recording"

    def __init__(self) -> None:
        self.events: list[dict] = []

    def emit(self, event: dict) -> None:
        self.events.append(event)


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


def _run_call(session_factory, exporter, *, sla_minutes: int, responded: bool) -> str:
    csa = CSATermsResult(
        counterparty_id="CP-1",
        threshold=1_000.0,
        mta=10_000.0,
        currency="USD",
        eligible_collateral=["cash"],
        haircuts={"cash": 0.0},
        rating_triggers=[],
        citations=CITATIONS,
    )
    sent = NotificationResult(
        notice_text="Mock notice.", slack_channel="C1", slack_ts="123.456", message_id="123.456"
    )
    state = _state()
    thread_id = thread_id_for(state.impact, state.counterparty_id)
    with (
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
            settings=Settings(_env_file=None, margin_call_sla_minutes=sla_minutes),
            lineage=MarginCallLineage(exporter, BUCKET),
        )
        start_run(graph, state)
        resume_run(graph, thread_id, {"decision": "approved", "approver_username": "alice"})
        resume_run(graph, thread_id, {"responded": True} if responded else {"check": True})
    return thread_id


def _names(datasets: list[dict]) -> list[str]:
    return [f"{d['namespace']}:{d['name']}" for d in datasets]


def _facet(event: dict) -> dict:
    return event["run"]["facets"]["marginmaestro_margin_call"]


# --- a full call ------------------------------------------------------------------


def test_a_full_call_emits_its_lineage_chain_on_one_run(session_factory):
    exporter = RecordingExporter()
    thread_id = _run_call(session_factory, exporter, sla_minutes=60, responded=True)

    events = exporter.events
    assert [_facet(e)["milestone"] for e in events] == [
        "call_raised",
        "approval",
        "notification",
        "sla_met",
    ]
    assert [e["eventType"] for e in events] == ["START", "RUNNING", "RUNNING", "COMPLETE"]
    # One process (job), one run per call.
    assert {(e["job"]["namespace"], e["job"]["name"]) for e in events} == {
        (JOB_NAMESPACE, JOB_NAME)
    }
    assert {e["run"]["runId"] for e in events} == {run_id_for(thread_id)}

    raised, approval, notification, resolution = events
    assert _names(raised["inputs"]) == [
        "custom:marginmaestro.price_event.evt-1",
        *[f"custom:marginmaestro.cloudsql.{t}" for t in CALC_INPUT_TABLES],
        f"gs://{BUCKET}:csa/CP-1.md",
    ]
    assert _names(raised["outputs"]) == [f"custom:marginmaestro.margin_call.{thread_id}"]
    assert [c["chunk_id"] for c in _facet(raised)["csa_citations"]] == [
        "csa/CP-1.md#Threshold",
        "csa/CP-1.md#Minimum Transfer Amount",
    ]
    assert _facet(raised)["trigger_event_id"] == "evt-1"

    assert approval["inputs"] == raised["outputs"]
    assert _names(approval["outputs"]) == [f"custom:marginmaestro.approval.{thread_id}"]
    assert _facet(approval)["decision"] == "approved"
    assert _facet(approval)["approver"] == "alice"

    assert notification["inputs"] == approval["outputs"]
    assert _names(notification["outputs"]) == [f"custom:marginmaestro.notification.{thread_id}"]
    assert _facet(notification)["channel"] == "slack"
    assert _facet(notification)["message_id"] == "123.456"

    assert resolution["inputs"] == notification["outputs"]
    assert _names(resolution["outputs"]) == [f"custom:marginmaestro.resolution.{thread_id}"]


def test_an_escalated_call_ends_with_the_incident(session_factory):
    exporter = RecordingExporter()
    thread_id = _run_call(session_factory, exporter, sla_minutes=0, responded=False)

    last = exporter.events[-1]
    assert _facet(last)["milestone"] == "escalated"
    assert _facet(last)["incident_number"] == "INC0010001"
    assert _names(last["outputs"]) == [f"custom:marginmaestro.escalation.{thread_id}"]
    assert last["eventType"] == "COMPLETE"


def test_lineage_carries_ids_never_amounts_or_names(session_factory):
    exporter = RecordingExporter()
    _run_call(session_factory, exporter, sla_minutes=60, responded=True)

    text = str(exporter.events)
    assert "Acme Capital" not in text  # confidential: counterparties.name
    assert "call_amount" not in text and "500.0" not in text


def test_export_failure_never_fails_the_call(session_factory):
    exporter = RecordingExporter()
    exporter.emit = MagicMock(side_effect=RuntimeError("lineage API down"))  # type: ignore[method-assign]

    with patch("governance.lineage.logger") as logger:
        thread_id = _run_call(session_factory, exporter, sla_minutes=60, responded=True)

    assert exporter.emit.call_count == 4  # every milestone was attempted
    warnings = [c for c in logger.warning.call_args_list if c.args[0] == "lineage_export_failed"]
    assert len(warnings) == 4
    assert warnings[0].kwargs["thread_id"] == thread_id


def test_a_rejected_call_completes_at_the_approval():
    exporter = RecordingExporter()
    MarginCallLineage(exporter).approval(_state(), "evt-1:CP-1", "rejected", "bob")

    assert exporter.events[0]["eventType"] == "COMPLETE"
    assert _facet(exporter.events[0])["decision"] == "rejected"


def test_a_manager_signature_is_its_own_milestone():
    exporter = RecordingExporter()
    MarginCallLineage(exporter).approval(
        _state(), "evt-1:CP-1", "approved", "carol", second_signature=True
    )

    assert _facet(exporter.events[0])["milestone"] == "manager_approval"
    assert exporter.events[0]["eventType"] == "RUNNING"


def test_disabled_lineage_emits_nothing():
    exporter = NoLineageExporter()
    lineage = MarginCallLineage(exporter)
    assert not lineage.enabled
    lineage.resolved(_state(), "evt-1:CP-1", "sla_met")  # no error, nothing sent
    assert exporter.emit({}) is None


def test_documents_fall_back_to_custom_names_without_a_gcs_bucket():
    assert document_dataset(None, "csa/CP-1.md") == {
        "namespace": "custom",
        "name": "marginmaestro.documents.csa/CP-1.md",
    }


def test_run_id_is_a_stable_uuid_per_call():
    first, again, other = (
        run_id_for("evt-1:CP-1"),
        run_id_for("evt-1:CP-1"),
        run_id_for("evt-1:CP-2"),
    )

    assert first == again  # deterministic: a replay reuses the run
    assert first != other
    assert len(first) == 36


# --- Data Lineage API exporter -------------------------------------------------------


def test_data_lineage_exporter_posts_the_event_to_the_openlineage_endpoint():
    session = MagicMock()
    exporter = DataLineageExporter("marginmaestro-demo", "us-central1", session=session)

    exporter.emit({"eventType": "START"})

    session.post.assert_called_once_with(
        "https://datalineage.googleapis.com/v1/projects/marginmaestro-demo/locations/"
        "us-central1:processOpenLineageRunEvent",
        json={"eventType": "START"},
        timeout=10,
    )
    session.post.return_value.raise_for_status.assert_called_once()


def test_data_lineage_exporter_raises_on_http_errors():
    session = MagicMock()
    session.post.return_value.raise_for_status.side_effect = RuntimeError("403")
    with pytest.raises(RuntimeError, match="403"):
        DataLineageExporter("p", "l", session=session).emit({})


def test_data_lineage_exporter_authenticates_with_default_credentials():
    with (
        patch("google.auth.default", return_value=(MagicMock(), "p")) as default,
        patch("google.auth.transport.requests.AuthorizedSession") as authorized,
    ):
        DataLineageExporter("p", "l").emit({})

    default.assert_called_once_with(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    authorized.return_value.post.assert_called_once()


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_exporter_selection():
    assert isinstance(get_lineage_exporter(_settings()), NoLineageExporter)
    exporter = get_lineage_exporter(
        _settings(lineage_exporter="datalineage", gcp_project_id="marginmaestro-demo")
    )
    assert isinstance(exporter, DataLineageExporter)
    with pytest.raises(ValueError, match="GCP_PROJECT_ID"):
        get_lineage_exporter(_settings(lineage_exporter="datalineage"))
    with pytest.raises(ValueError, match="LINEAGE_EXPORTER"):
        get_lineage_exporter(_settings(lineage_exporter="kafka"))


def test_documents_use_the_gcs_bucket_only_when_documents_live_there():
    on_gcs = get_margin_call_lineage(_settings(document_store="gcs", gcs_documents_bucket=BUCKET))
    on_s3 = get_margin_call_lineage(_settings(document_store="s3", gcs_documents_bucket=BUCKET))
    assert on_gcs._bucket == BUCKET
    assert on_s3._bucket is None
