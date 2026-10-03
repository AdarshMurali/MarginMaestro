"""MM-127: trace exporter selection, one trace per orchestrator run, span
flushing, and the Cloud Logging fields on every log line."""

from datetime import UTC, date, datetime
from unittest.mock import MagicMock, patch

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from agents.communication import NotificationResult
from agents.orchestrator import (
    MarginCallState,
    build_orchestrator_graph,
    resume_run,
    start_run,
    thread_id_for,
)
from api.logging_config import cloud_logging_fields
from config.settings import Settings
from observability import tracing
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

# --- exporter selection -------------------------------------------------------------


def test_cloud_trace_exporter_for_the_project():
    with patch("opentelemetry.exporter.cloud_trace.CloudTraceSpanExporter") as exporter:
        result = tracing._exporter(
            Settings(_env_file=None, trace_exporter="cloudtrace", gcp_project_id="proj")
        )

    assert result is exporter.return_value
    exporter.assert_called_once_with(project_id="proj")


def test_cloud_trace_needs_a_project():
    with pytest.raises(ValueError, match="GCP_PROJECT_ID"):
        tracing._exporter(Settings(_env_file=None, trace_exporter="cloudtrace"))


@pytest.mark.parametrize(
    "settings",
    [
        Settings(_env_file=None, trace_exporter="none"),
        Settings(_env_file=None, trace_exporter="otlp", otel_exporter_otlp_endpoint=""),
    ],
)
def test_no_exporter(settings):
    assert tracing._exporter(settings) is None


def test_otlp_is_the_default():
    with patch("observability.tracing.OTLPSpanExporter") as exporter:
        assert tracing._exporter(Settings(_env_file=None)) is exporter.return_value


def test_unknown_exporter_fails_loud():
    with pytest.raises(ValueError, match="TRACE_EXPORTER"):
        tracing._exporter(Settings(_env_file=None, trace_exporter="zipkin"))


def test_flush_spans_forces_an_export():
    provider = MagicMock()
    with patch("observability.tracing.trace.get_tracer_provider", return_value=provider):
        tracing.flush_spans(1_000)

    provider.force_flush.assert_called_once_with(1_000)


def test_flush_spans_tolerates_a_provider_without_flush():
    with patch("observability.tracing.trace.get_tracer_provider", return_value=object()):
        tracing.flush_spans()


# --- one trace per run ----------------------------------------------------------------------


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
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
    return factory


@pytest.fixture
def spans():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    with patch("agents.orchestrator.tracer", provider.get_tracer("test")):
        yield exporter


def test_each_invocation_is_one_trace_with_the_steps_inside(session_factory, spans):
    feed = MagicMock()
    feed.get_prices.return_value = {
        "TSLA": PriceQuote(ticker="TSLA", price=500.0, as_of=datetime.now(UTC), source="yfinance")
    }
    graph = build_orchestrator_graph(
        session_factory=session_factory,
        market_feed=feed,
        settings=Settings(_env_file=None),
        sla_scheduler=MagicMock(),
    )
    impact = ImpactSet(
        event_id="evt-1",
        event_type=MarketEventType.PRICE_SHOCK,
        counterparty_ids=["CP-1"],
        reason="TSLA moved 400.0% vs prior close",
        occurred_at=datetime.now(UTC),
    )
    state = MarginCallState(correlation_id="evt-1", impact=impact, counterparty_id="CP-1")
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
    sent = NotificationResult(notice_text="n", slack_channel="C1", slack_ts="1.2")
    with (
        patch("agents.orchestrator.answer_csa_terms", return_value=csa),
        patch("agents.orchestrator.draft_margin_call_notice", return_value="n"),
        patch("agents.orchestrator.send_slack_notice", return_value=sent),
    ):
        start_run(graph, state)
        resume_run(graph, thread_id_for(impact, "CP-1"), {"decision": "approved"})

    finished = spans.get_finished_spans()
    roots = [s for s in finished if s.name == "margin_call_run"]
    assert [r.attributes["margincall.phase"] for r in roots] == ["start", "resume"]
    assert {r.attributes["margincall.thread_id"] for r in roots} == {"evt-1:CP-1"}
    assert roots[1].attributes["margincall.counterparty_id"] == "CP-1"

    by_trace = {r.context.trace_id: r for r in roots}
    steps = [s for s in finished if s.name != "margin_call_run"]
    assert {s.name for s in steps} >= {
        "compute_exposure",
        "fetch_csa_terms",
        "evaluate_breach",
        "send_notification",
    }
    for step in steps:
        assert step.context.trace_id in by_trace, f"{step.name} is outside its run's trace"
        assert step.parent is not None


# --- Cloud Logging fields --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("level", "severity"), [("info", "INFO"), ("warning", "WARNING"), ("error", "ERROR")]
)
def test_severity_follows_the_level(level, severity):
    assert cloud_logging_fields(None, "info", {"level": level})["severity"] == severity


def test_lines_inside_a_span_link_to_their_trace():
    tracer = TracerProvider().get_tracer("test")
    with (
        patch(
            "api.logging_config.get_settings",
            return_value=Settings(_env_file=None, gcp_project_id="proj"),
        ),
        tracer.start_as_current_span("work") as span,
    ):
        fields = cloud_logging_fields(None, "info", {"level": "info", "event": "x"})

    context = span.get_span_context()
    assert fields["logging.googleapis.com/trace"] == f"projects/proj/traces/{context.trace_id:032x}"
    assert fields["logging.googleapis.com/spanId"] == f"{context.span_id:016x}"
    assert fields["logging.googleapis.com/trace_sampled"] is True


def test_no_trace_fields_outside_a_span_or_without_a_project():
    assert "logging.googleapis.com/trace" not in cloud_logging_fields(None, "info", {})
    tracer = TracerProvider().get_tracer("test")
    with (
        patch("api.logging_config.get_settings", return_value=Settings(_env_file=None)),
        tracer.start_as_current_span("work"),
    ):
        assert "logging.googleapis.com/trace" not in cloud_logging_fields(None, "info", {})
