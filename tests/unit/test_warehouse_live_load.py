"""MM-141: the live book's daily warehouse load -- a real margin call run on
the orchestrator graph (SQLite, LLM and notifiers mocked), then loaded: the
exposure is recomputed with the calc engine from Cloud SQL data and the CSA
terms the run extracted (no LLM call in the load), the call's lifecycle comes
from the audit trail, and every table slice is replaced idempotently."""

from datetime import UTC, date, datetime, timedelta
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
from calc.models import CSATerms
from config.settings import Settings
from persistence.db.models import (
    Base,
    CollateralItemORM,
    CounterpartyORM,
    PortfolioORM,
    PositionORM,
    PriceHistoryORM,
    RatingORM,
    ReferenceRateORM,
)
from persistence.models import RatingGrade, RatingTrigger
from rag.models import Citation, CSATermsResult
from streaming.market_feed import PriceQuote
from streaming.schemas import ImpactSet, MarketEventType
from warehouse import live_load
from warehouse.live_load import (
    NoClosesError,
    RunRecord,
    Snapshot,
    csa_versions,
    exposure_and_positions,
    load_live_day,
    margin_call_row,
    read_runs,
    read_snapshot,
    terms_on,
)
from warehouse.schemas import (
    FACT_DAILY_EXPOSURE,
    FACT_MARGIN_CALL,
    FACT_POSITION_DAILY,
    SIM_END_DATE,
    BookDateError,
)

TODAY = datetime.now(UTC).date()
PRIOR = TODAY - timedelta(days=1)


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        session.add(
            CounterpartyORM(id="CP-1", name="Acme Capital", type="Bank", country="US", tier="elite")
        )
        session.add(CounterpartyORM(id="CP-2", name="Bare Fund", type="Hedge Fund", country="UK"))
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
        for day, price in ((PRIOR, 100.0), (TODAY, 110.0)):
            session.add(
                PriceHistoryORM(
                    ticker="TSLA", price_date=day, price=price, currency="USD", source="eod"
                )
            )
        session.add(ReferenceRateORM(series_id="VIXCLS", rate_date=PRIOR, value=30.0))
        session.add(ReferenceRateORM(series_id="DGS10", rate_date=TODAY, value=4.1))
        session.add(RatingORM(id="R1", counterparty_id="CP-1", grade="A", rating_date=PRIOR))
        session.add(
            CollateralItemORM(
                id="C1",
                counterparty_id="CP-1",
                collateral_type="cash",
                value_usd=20_000.0,
                haircut_pct=0.5,
            )
        )
        session.commit()
    return factory


def _run_call(session_factory, *, responded: bool):
    csa = CSATermsResult(
        counterparty_id="CP-1",
        threshold=1_000.0,
        mta=10_000.0,
        currency="USD",
        eligible_collateral=["cash"],
        haircuts={"cash": 0.0},
        rating_triggers=[],
        citations=[Citation(source_file="csa/CP-1.md", section="Threshold")],
    )
    sent = NotificationResult(
        notice_text="Mock notice.", slack_channel="C1", slack_ts="1.2", message_id="1.2"
    )
    impact = ImpactSet(
        event_id="evt-1",
        event_type=MarketEventType.DAILY_MARGIN_RUN,
        counterparty_ids=["CP-1"],
        reason="Daily margin run",
        occurred_at=datetime.now(UTC),
    )
    state = MarginCallState(correlation_id="corr-1", impact=impact, counterparty_id="CP-1")
    feed = MagicMock()
    feed.get_prices.return_value = {
        "TSLA": PriceQuote(ticker="TSLA", price=500.0, as_of=datetime.now(UTC), source="yfinance")
    }
    with (
        patch("agents.orchestrator.answer_csa_terms", return_value=csa),
        patch("agents.orchestrator.draft_margin_call_notice", return_value="Mock notice."),
        patch("agents.orchestrator.send_slack_notice", return_value=sent),
        patch("agents.orchestrator.draft_sla_met_notice", return_value="Met."),
        patch("agents.orchestrator.retrieve_escalation_procedure", return_value="Escalate."),
        patch(
            "agents.orchestrator.open_servicenow_incident",
            return_value=IncidentResult(incident_number="INC1", sys_id="x", urgency="2"),
        ),
    ):
        graph = build_orchestrator_graph(
            session_factory=session_factory,
            market_feed=feed,
            settings=Settings(_env_file=None, margin_call_sla_minutes=0 if not responded else 60),
        )
        thread_id = thread_id_for(state.impact, state.counterparty_id)
        start_run(graph, state)
        resume_run(graph, thread_id, {"decision": "approved", "approver_username": "alice"})
        resume_run(
            graph, thread_id, {"decision": "approved", "approver_username": "manager1"}
        )  # elite: second signature
        resume_run(graph, thread_id, {"responded": True} if responded else {"check": True})
    return graph, thread_id


def _fake_client():
    client = MagicMock()
    client.replace.side_effect = lambda table, start, end, rows, param_type="DATE": len(list(rows))
    return client


def _rows(client, table):
    for call in client.replace.call_args_list:
        if call.args[0] is table:
            return call.args[1], call.args[2], list(call.args[3])
    raise AssertionError(f"{table.name} not loaded")


# --- the whole load ---------------------------------------------------------------------


def test_a_full_day_is_loaded_from_a_real_run(session_factory, monkeypatch):
    graph, thread_id = _run_call(session_factory, responded=True)
    refresh = MagicMock()
    monkeypatch.setattr(live_load, "refresh_reports", refresh)
    client = _fake_client()

    with patch("agents.orchestrator.answer_csa_terms") as llm:
        result = load_live_day(client, session_factory, graph)
        llm.assert_not_called()  # the load never extracts CSA terms itself

    assert result.as_of == TODAY
    start, end, exposure = _rows(client, FACT_DAILY_EXPOSURE)
    assert (start, end) == (TODAY, TODAY)
    [row] = exposure
    values = dict(zip(FACT_DAILY_EXPOSURE.column_names, row, strict=True))
    # 1,000 TSLA 100 -> 110, VIX 30 (x1.5): VM 10,000; IM 0.15 x 110,000 x 1.5.
    assert values["variation_margin"] == pytest.approx(10_000)
    assert values["initial_margin"] == pytest.approx(24_750)
    assert values["exposure"] == pytest.approx(34_750)
    assert values["collateral_held"] == pytest.approx(10_000)  # 20,000 after a 50% haircut
    assert values["threshold"] == 1_000.0 and values["mta"] == 10_000.0
    assert values["call_due"] == pytest.approx(34_750 - 1_000 - 10_000)
    assert values["breached"] is True and values["book"] == "live"
    assert values["rating"] == "A" and values["csa_version"] == 1
    assert result.skipped == ["CP-2: no positions"]

    _, _, positions = _rows(client, FACT_POSITION_DAILY)
    assert positions == [
        (TODAY, "live", "CP-1", "POS-1", "TSLA", "equity", 1000.0, 110.0, 110_000.0)
    ]

    start, end, calls = _rows(client, FACT_MARGIN_CALL)
    assert end == TODAY and start == max(
        TODAY - timedelta(days=13), SIM_END_DATE + timedelta(days=1)
    )
    [call] = calls
    call_values = dict(zip(FACT_MARGIN_CALL.column_names, call, strict=True))
    assert call_values["call_id"] == thread_id
    assert call_values["trigger_type"] == "daily_margin_run"
    assert call_values["approver"] == "alice"
    assert call_values["approved_at"] is not None and call_values["manager_approved_at"] is not None
    assert call_values["acknowledged_at"] is not None and call_values["escalated_at"] is None
    assert call_values["sla_outcome"] == "met" and call_values["status"] == "sla_met"
    assert call_values["channel"] == "slack"

    replaced_dims = {
        call.args[0].name: call.args[1:3]
        for call in client.replace.call_args_list
        if call.args[0].name.startswith("dim_")
    }
    assert replaced_dims == {
        "dim_counterparty": (1, 1),
        "dim_instrument": (1, 1),
        "dim_csa_terms": (1, 1),
    }
    refresh.assert_called_once_with(client, start, TODAY)


def test_an_escalated_call_records_the_escalation(session_factory, monkeypatch):
    graph, _ = _run_call(session_factory, responded=False)
    with session_factory() as session:
        [run] = read_runs(graph, session)
    row = dict(zip(FACT_MARGIN_CALL.column_names, margin_call_row(run), strict=True))
    assert row["escalated_at"] is not None and row["acknowledged_at"] is None
    assert row["sla_outcome"] == "breached" and row["status"] == "escalated"


def test_no_closes_for_the_day_is_an_error(session_factory):
    graph = MagicMock()
    with pytest.raises(NoClosesError):
        load_live_day(_fake_client(), session_factory, graph, TODAY + timedelta(days=1))


def test_the_live_book_never_writes_simulated_dates(session_factory):
    with pytest.raises(BookDateError):
        load_live_day(_fake_client(), session_factory, MagicMock(), SIM_END_DATE)


def test_empty_price_history_is_an_error():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with pytest.raises(NoClosesError, match="empty"):
        load_live_day(_fake_client(), sessionmaker(bind=engine), MagicMock())


# --- pieces -----------------------------------------------------------------------------------


def test_snapshot_reads_closes_prior_closes_vix_and_rates(session_factory):
    with session_factory() as session:
        snapshot = read_snapshot(session, TODAY)
    assert snapshot.closes == {"TSLA": 110.0}
    assert snapshot.prior_closes == {"TSLA": 100.0}
    assert snapshot.vix == 30.0  # the latest VIXCLS on or before the day
    assert snapshot.rates == {"DGS10": 4.1}
    cp1 = next(cp for cp in snapshot.counterparties if cp.id == "CP-1")
    assert cp1.tier == "elite" and cp1.rating is RatingGrade.A


def _run(counterparty: str, when: datetime, terms: CSATerms | None, **values) -> RunRecord:
    impact = MagicMock()
    impact.occurred_at = when
    return RunRecord(
        thread_id=f"t-{when.isoformat()}",
        values={"counterparty_id": counterparty, "impact": impact, "csa_terms": terms, **values},
    )


def test_csa_terms_become_scd2_versions_when_they_change():
    t1 = CSATerms(threshold=100.0, mta=10.0)
    t2 = CSATerms(threshold=50.0, mta=10.0)
    day = datetime(2026, 9, 1, tzinfo=UTC)
    runs = [
        _run("CP-1", day + timedelta(days=2), t1),
        _run("CP-1", day, t1),
        _run("CP-1", day + timedelta(days=5), t2),
        _run("CP-2", day, None),
    ]
    versions = csa_versions(runs)
    assert versions["CP-1"] == [(date(2026, 9, 1), t1), (date(2026, 9, 6), t2)]
    assert "CP-2" not in versions
    assert terms_on(versions["CP-1"], date(2026, 9, 3)) == (1, t1)
    assert terms_on(versions["CP-1"], date(2026, 9, 6)) == (2, t2)
    assert terms_on(versions["CP-1"], date(2026, 8, 1)) == (1, t1)  # before any run
    assert terms_on([], date(2026, 9, 1)) is None


def test_dimension_rows_carry_scd2_validity_and_triggers():
    t1 = CSATerms(
        threshold=100.0,
        mta=10.0,
        rating_triggers=[RatingTrigger(below_grade=RatingGrade.B, reduced_threshold=0.0)],
    )
    t2 = CSATerms(threshold=50.0, mta=10.0)
    versions = {"CP-1": [(date(2026, 9, 1), t1), (date(2026, 9, 6), t2)]}
    snapshot = Snapshot(TODAY, [], {}, {}, None, {})
    csa = live_load.dimension_rows(snapshot, versions)["dim_csa_terms"]
    assert [(r[3], r[4], r[5], r[6]) for r in csa] == [
        (1, date(2026, 9, 1), date(2026, 9, 5), False),
        (2, date(2026, 9, 6), date(9999, 12, 31), True),
    ]
    assert csa[0][10:12] == ("B", 0.0) and csa[1][10:12] == (None, None)


def test_counterparties_that_cant_be_priced_are_skipped_with_a_reason(session_factory):
    with session_factory() as session:
        snapshot = read_snapshot(session, TODAY)
    terms = CSATerms(threshold=0.0, mta=0.0)
    assert exposure_and_positions(snapshot, {})[2] == [
        "CP-1: no CSA terms extracted by any run yet",
        "CP-2: no positions",
    ]
    no_vix = Snapshot(
        TODAY, snapshot.counterparties, snapshot.closes, snapshot.prior_closes, None, {}
    )
    assert "no VIXCLS" in exposure_and_positions(no_vix, {"CP-1": [(TODAY, terms)]})[2][0]
    no_prior = Snapshot(TODAY, snapshot.counterparties, snapshot.closes, {}, 20.0, {})
    assert "no close for TSLA" in exposure_and_positions(no_prior, {"CP-1": [(TODAY, terms)]})[2][0]


def test_runs_without_a_raised_call_are_not_facts():
    breach = MagicMock(breached=False)
    assert margin_call_row(_run("CP-1", datetime.now(UTC), None, breach_result=breach)) is None
    held = MagicMock(breached=True)
    run = _run("CP-1", datetime.now(UTC), None, breach_result=held, materiality="below_mta")
    assert margin_call_row(run) is None
    assert margin_call_row(_run("CP-1", datetime.now(UTC), None)) is None
