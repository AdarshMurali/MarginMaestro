"""MM-125 (Phase G5b): margin-call policy, end to end on the real graph.

Books mirror the seeded (seed 42) HPE holders that the live 2026-10-02 run
called: CP-1 (-439 HPE), CP-3 (247), CP-7 (742), each with a large NVDA
position that puts it in a *standing* breach. CSA MTAs are the real ones
(CP-1 11,000; CP-3 19,000; CP-7 47,000). The LLM (CSA extraction, notice
drafting) and Slack are mocked; every figure is computed by the calc engine.
"""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from agents.communication import NotificationResult
from agents.margin_policy import (
    LEASE_TTL,
    CounterpartyBusyError,
    TriggerAction,
    counterparty_lease,
    dispatch_trigger,
)
from agents.orchestrator import (
    build_orchestrator_graph,
    find_open_call,
    open_call_stage,
    resume_run,
)
from api.margin_calls import _lifecycle_status, list_margin_calls
from api.schemas import MarginCallLifecycleStatus
from calc.models import BreachResult, PriceMove
from config.settings import Settings
from persistence.audit import list_audit_events
from persistence.db.models import (
    Base,
    CollateralItemORM,
    CounterpartyORM,
    PortfolioORM,
    PositionORM,
    PriceHistoryORM,
    ProcessedEventORM,
    ReferenceRateORM,
)
from persistence.models import CounterpartyTier
from rag.models import CSATermsResult
from streaming.event_agent import handle_price_message
from streaming.impact_consumer import daily_margin_run_impact, handle_impact
from streaming.market_feed import PriceQuote
from streaming.schemas import ImpactSet, MarketEventType

HPE_QUANTITIES = {"CP-1": -439.0, "CP-3": 247.0, "CP-7": 742.0}
MTA = {"CP-1": 11_000.0, "CP-3": 19_000.0, "CP-7": 47_000.0}
THRESHOLD = 100_000.0
NVDA_QUANTITY = 10_000.0
PRIOR_CLOSE = {"HPE": 65.07, "NVDA": 180.0}
SHOCK_DAY = datetime(2026, 10, 2, 15, 30, tzinfo=UTC)


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        for cp, hpe in HPE_QUANTITIES.items():
            session.add(CounterpartyORM(id=cp, name=cp, type="Bank", country="US"))
            session.add(PortfolioORM(id=f"PF-{cp}", counterparty_id=cp, currency="USD"))
            for ticker, quantity in (("HPE", hpe), ("NVDA", NVDA_QUANTITY)):
                session.add(
                    PositionORM(
                        id=f"POS-{cp}-{ticker}",
                        portfolio_id=f"PF-{cp}",
                        ticker=ticker,
                        asset_class="equity",
                        quantity=quantity,
                        trade_date=date(2026, 1, 1),
                    )
                )
            session.add(
                CollateralItemORM(
                    id=f"C-{cp}",
                    counterparty_id=cp,
                    collateral_type="cash",
                    value_usd=0.0,
                    haircut_pct=0.0,
                )
            )
        for ticker, price in PRIOR_CLOSE.items():
            session.add(
                PriceHistoryORM(
                    ticker=ticker,
                    price_date=date(2026, 10, 1),
                    price=price,
                    currency="USD",
                    source="eod",
                )
            )
        session.add(ReferenceRateORM(series_id="VIXCLS", rate_date=date(2026, 10, 1), value=20.0))
        session.commit()
    return factory


class _Feed:
    """Current prices, changeable between triggers."""

    def __init__(self) -> None:
        self.prices = {"HPE": 69.88, "NVDA": 180.0}

    def get_prices(self, tickers: list[str]) -> dict[str, PriceQuote]:
        return {
            t: PriceQuote(ticker=t, price=self.prices[t], as_of=datetime.now(UTC), source="test")
            for t in tickers
        }


def _csa(counterparty_id: str, **_: object) -> CSATermsResult:
    return CSATermsResult(
        counterparty_id=counterparty_id,
        threshold=THRESHOLD,
        mta=MTA[counterparty_id],
        currency="USD",
        eligible_collateral=["cash"],
        haircuts={"cash": 0.0},
        rating_triggers=[],
        citations=[],
    )


@pytest.fixture
def feed() -> _Feed:
    return _Feed()


@pytest.fixture
def graph(session_factory, feed):
    with (
        patch("agents.orchestrator.answer_csa_terms", side_effect=_csa) as csa,
        patch("agents.orchestrator.draft_margin_call_notice", return_value="notice"),
        patch(
            "agents.orchestrator.send_slack_notice",
            return_value=NotificationResult(notice_text="notice", slack_channel="C1", slack_ts="1"),
        ),
    ):
        graph = build_orchestrator_graph(
            session_factory=session_factory,
            market_feed=feed,
            settings=Settings(_env_file=None),
            sla_scheduler=MagicMock(),
        )
        graph.csa_mock = csa  # type: ignore[attr-defined]
        yield graph


def _calls(graph, session_factory):
    with session_factory() as session:
        return list_margin_calls(graph, session, Settings(_env_file=None)).margin_calls


def _open_calls(graph, session_factory, counterparty_id: str | None = None):
    return [
        c
        for c in _calls(graph, session_factory)
        if c.status
        in (
            MarginCallLifecycleStatus.AWAITING_APPROVAL,
            MarginCallLifecycleStatus.AWAITING_MANAGER_APPROVAL,
            MarginCallLifecycleStatus.AWAITING_SLA_RESPONSE,
        )
        and (counterparty_id is None or c.counterparty_id == counterparty_id)
    ]


def _daily_run(graph, session_factory, run_date: date = date(2026, 10, 2)):
    with session_factory() as session:
        impact = daily_margin_run_impact(session, run_date)
    return handle_impact(impact, session_factory, lambda: graph)


def _nvda_shock(event_id: str = "NVDA:2026-10-05:price_shock", to_price: float = 198.0):
    return ImpactSet(
        event_id=event_id,
        event_type=MarketEventType.PRICE_SHOCK,
        counterparty_ids=sorted(HPE_QUANTITIES),
        reason=f"NVDA moved vs prior close (180.0 -> {to_price})",
        occurred_at=datetime(2026, 10, 5, 15, tzinfo=UTC),
        price_moves=[PriceMove(ticker="NVDA", from_price=180.0, to_price=to_price)],
    )


def _audit_types(session_factory, thread_id: str) -> list[str]:
    correlation_id, counterparty_id = thread_id.rsplit(":", 1)
    with session_factory() as session:
        return [e.event_type for e in list_audit_events(session, correlation_id, counterparty_id)]


class TestExitCriteria:
    def test_replaying_the_hpe_move_raises_no_intraday_calls(self, graph, session_factory):
        """2026-10-02, HPE +7.4% ($65.07 -> $69.88): the Event Agent's real
        price path raises the impact; the gate holds every HPE holder."""
        quote = PriceQuote(ticker="HPE", price=69.88, as_of=SHOCK_DAY, source="yfinance")
        with session_factory() as session:
            impact = handle_price_message(session, quote, MagicMock(), Settings(_env_file=None))
        assert impact is not None
        assert impact.price_moves == [PriceMove(ticker="HPE", from_price=65.07, to_price=69.88)]

        outcomes = handle_impact(impact, session_factory, lambda: graph)

        assert [o.counterparty_id for o in outcomes] == ["CP-1", "CP-3", "CP-7"]
        for outcome in outcomes:
            assert outcome.breached is True  # the standing breach is real...
            assert outcome.call_amount is None  # ...but the HPE move raises no call
            assert "no intraday call" in (outcome.detail or "")
        assert _open_calls(graph, session_factory) == []
        statuses = {c.counterparty_id: c.status for c in _calls(graph, session_factory)}
        assert set(statuses.values()) == {MarginCallLifecycleStatus.BELOW_MATERIALITY}
        cp7 = next(o for o in outcomes if o.counterparty_id == "CP-7")
        assert "increased your exposure by USD 4,104.37" in (cp7.detail or "")

    def test_daily_run_raises_each_standing_breach_once(self, graph, session_factory):
        first = _daily_run(graph, session_factory)
        again = _daily_run(graph, session_factory)  # a Scheduler retry, same day

        assert [o.action for o in first] == [TriggerAction.STARTED] * 3
        assert again == []
        open_calls = _open_calls(graph, session_factory)
        assert sorted(c.counterparty_id for c in open_calls) == ["CP-1", "CP-3", "CP-7"]
        for call in open_calls:
            assert call.status is MarginCallLifecycleStatus.AWAITING_APPROVAL
            assert call.event_type == "daily_margin_run"
            assert call.rationale is not None
            assert call.rationale.startswith("Daily margin run: Your exposure of USD ")
            assert "is due" in call.rationale

    def test_a_second_shock_updates_the_open_call(self, graph, session_factory, feed):
        _daily_run(graph, session_factory)
        before = {c.counterparty_id: c for c in _open_calls(graph, session_factory)}

        feed.prices["NVDA"] = 198.0
        outcomes = handle_impact(_nvda_shock(), session_factory, lambda: graph)

        assert [o.action for o in outcomes] == [TriggerAction.UPDATED] * 3
        after = {c.counterparty_id: c for c in _open_calls(graph, session_factory)}
        assert len(after) == 3  # still one open call each, no second call
        for cp, call in after.items():
            assert call.thread_id == before[cp].thread_id
            assert call.call_amount > before[cp].call_amount
            assert call.updated_by == ["NVDA:2026-10-05:price_shock"]
            assert call.status is MarginCallLifecycleStatus.AWAITING_APPROVAL  # gate re-armed
            assert "The NVDA move (USD 180.00 to USD 198.00) increased your exposure" in (
                call.rationale or ""
            )
            assert "open_call_updated" in _audit_types(session_factory, call.thread_id)

    def test_replaying_the_same_event_is_idempotent(self, graph, session_factory, feed):
        _daily_run(graph, session_factory)
        feed.prices["NVDA"] = 198.0
        handle_impact(_nvda_shock(), session_factory, lambda: graph)
        amounts = {c.counterparty_id: c.call_amount for c in _open_calls(graph, session_factory)}

        assert handle_impact(_nvda_shock(), session_factory, lambda: graph) == []
        # Even past the claim (e.g. the /simulate path), the open call has
        # already applied this trigger.
        outcome = dispatch_trigger(graph, _nvda_shock(), "CP-3", session_factory)

        assert outcome.action is TriggerAction.UNCHANGED
        assert {
            c.counterparty_id: c.call_amount for c in _open_calls(graph, session_factory)
        } == amounts
        assert len(_calls(graph, session_factory)) == 3


class TestOpenCallPolicy:
    def test_an_immaterial_event_leaves_the_open_call_alone(self, graph, session_factory):
        _daily_run(graph, session_factory)
        before = {c.counterparty_id: c for c in _open_calls(graph, session_factory)}
        hpe = ImpactSet(
            event_id="HPE:2026-10-05:price_shock",
            event_type=MarketEventType.PRICE_SHOCK,
            counterparty_ids=["CP-7"],
            reason="HPE moved 7.4% vs prior close",
            occurred_at=SHOCK_DAY,
            price_moves=[PriceMove(ticker="HPE", from_price=65.07, to_price=69.88)],
        )
        csa_calls = graph.csa_mock.call_count

        (outcome,) = handle_impact(hpe, session_factory, lambda: graph)

        assert outcome.action is TriggerAction.UNCHANGED
        assert outcome.thread_id == before["CP-7"].thread_id
        assert "no intraday call" in (outcome.detail or "")
        assert graph.csa_mock.call_count == csa_calls  # MTA from the open call: no LLM
        after = _open_calls(graph, session_factory, "CP-7")
        assert [c.call_amount for c in after] == [before["CP-7"].call_amount]
        assert after[0].updated_by == []
        assert "trigger_below_materiality" in _audit_types(session_factory, outcome.thread_id)

    def test_a_call_with_one_signature_is_never_changed(self, graph, session_factory, feed):
        """Elite tier: approved by the first approver, waiting for the
        manager. A material shock must not change what was signed."""
        with session_factory() as session:
            session.get(CounterpartyORM, "CP-7").tier = CounterpartyTier.ELITE.value
            session.commit()
        _daily_run(graph, session_factory)
        (call,) = _open_calls(graph, session_factory, "CP-7")
        resume_run(graph, call.thread_id, {"decision": "approved", "approver_username": "a"})

        feed.prices["NVDA"] = 198.0
        outcome = dispatch_trigger(graph, _nvda_shock(), "CP-7", session_factory)

        assert outcome.action is TriggerAction.UNCHANGED
        assert "already been approved or sent" in (outcome.detail or "")
        (after,) = _open_calls(graph, session_factory, "CP-7")
        assert after.status is MarginCallLifecycleStatus.AWAITING_MANAGER_APPROVAL
        assert after.call_amount == call.call_amount
        assert "trigger_absorbed_by_open_call" in _audit_types(session_factory, call.thread_id)

    def test_a_notified_call_is_never_changed(self, graph, session_factory, feed):
        _daily_run(graph, session_factory)
        (call,) = _open_calls(graph, session_factory, "CP-3")
        resume_run(graph, call.thread_id, {"decision": "approved", "approver_username": "a"})

        feed.prices["NVDA"] = 198.0
        outcome = dispatch_trigger(graph, _nvda_shock(), "CP-3", session_factory)

        assert outcome.action is TriggerAction.UNCHANGED
        (after,) = _open_calls(graph, session_factory, "CP-3")
        assert after.status is MarginCallLifecycleStatus.AWAITING_SLA_RESPONSE
        assert after.call_amount == call.call_amount

    def test_an_updated_call_is_approved_at_its_new_amount(self, graph, session_factory, feed):
        _daily_run(graph, session_factory)
        feed.prices["NVDA"] = 198.0
        handle_impact(_nvda_shock(), session_factory, lambda: graph)
        (call,) = _open_calls(graph, session_factory, "CP-3")

        result = resume_run(
            graph, call.thread_id, {"decision": "approved", "approver_username": "a"}
        )

        assert result["notification_sent_at"] is not None
        assert result["breach_result"].call_amount == pytest.approx(call.call_amount)

    def test_the_daily_run_withdraws_an_unapproved_call_no_longer_in_breach(
        self, graph, session_factory, feed
    ):
        _daily_run(graph, session_factory)
        (call,) = _open_calls(graph, session_factory, "CP-3")

        feed.prices["NVDA"] = 10.0  # the book's exposure collapses below the threshold
        outcomes = _daily_run(graph, session_factory, date(2026, 10, 5))

        cp3 = next(o for o in outcomes if o.counterparty_id == "CP-3")
        assert cp3.action is TriggerAction.UPDATED
        assert cp3.thread_id == call.thread_id
        assert cp3.breached is False
        assert _open_calls(graph, session_factory) == []
        statuses = {c.thread_id: c.status for c in _calls(graph, session_factory)}
        assert statuses[call.thread_id] is MarginCallLifecycleStatus.NO_BREACH

    def test_a_resolved_call_lets_the_next_trigger_raise_a_new_one(self, graph, session_factory):
        _daily_run(graph, session_factory)
        (call,) = _open_calls(graph, session_factory, "CP-3")
        resume_run(graph, call.thread_id, {"decision": "rejected", "approver_username": "a"})

        outcomes = _daily_run(graph, session_factory, date(2026, 10, 5))

        cp3 = next(o for o in outcomes if o.counterparty_id == "CP-3")
        assert cp3.action is TriggerAction.STARTED
        assert cp3.thread_id == "daily-margin-run:2026-10-05:CP-3"

    def test_a_material_event_with_no_open_call_raises_a_call(self, graph, session_factory, feed):
        feed.prices["NVDA"] = 198.0

        outcomes = handle_impact(_nvda_shock(), session_factory, lambda: graph)

        assert [o.action for o in outcomes] == [TriggerAction.STARTED] * 3
        assert all(o.call_amount for o in outcomes)
        assert len(_open_calls(graph, session_factory)) == 3


class TestFindOpenCall:
    def test_matches_the_counterparty_exactly(self, graph, session_factory):
        _daily_run(graph, session_factory)

        with session_factory() as session:
            found = find_open_call(graph, session, "CP-3")
            assert find_open_call(graph, session, "CP-") is None
            assert find_open_call(graph, session, "CP-33") is None

        assert found is not None and found[0] == "daily-margin-run:2026-10-02:CP-3"

    def test_most_recent_of_several_legacy_open_calls_wins(self, graph, session_factory, feed):
        """Calls raised before this policy can leave two open calls."""
        feed.prices["NVDA"] = 198.0
        with session_factory() as session:
            first = daily_margin_run_impact(session, date(2026, 10, 1))
            second = daily_margin_run_impact(session, date(2026, 10, 2))
        second = second.model_copy(update={"occurred_at": first.occurred_at + timedelta(hours=1)})
        from agents.orchestrator import MarginCallState, start_run

        for impact in (first, second):  # bypass the policy, like pre-MM-125 code
            start_run(graph, MarginCallState(impact=impact, counterparty_id="CP-3"))

        with session_factory() as session:
            found = find_open_call(graph, session, "CP-3")

        assert found is not None and found[0] == "daily-margin-run:2026-10-02:CP-3"


class TestOpenCallStage:
    BREACH = BreachResult(breached=True, call_amount=1.0)

    @pytest.mark.parametrize(
        ("values", "expected"),
        [
            ({}, None),
            ({"breach_result": BreachResult(breached=False, call_amount=0)}, None),
            ({"breach_result": BREACH, "materiality": "below_mta"}, None),
            ({"breach_result": BREACH}, "awaiting_approval"),
            ({"breach_result": BREACH, "approval_decision": "rejected"}, None),
            ({"breach_result": BREACH, "approval_decision": "disputed"}, None),
            (
                {"breach_result": BREACH, "approval_decision": "approved"},
                "awaiting_manager_approval",
            ),
            (
                {"breach_result": BREACH, "approval_decision": "adjusted"},
                "awaiting_manager_approval",
            ),
            (
                {"breach_result": BREACH, "notification_sent_at": SHOCK_DAY},
                "awaiting_sla_response",
            ),
            (
                {"breach_result": BREACH, "notification_sent_at": SHOCK_DAY, "sla_outcome": "met"},
                None,
            ),
            ({"breach_result": BREACH, "escalation_result": object()}, None),
        ],
    )
    def test_stage(self, values, expected) -> None:
        assert open_call_stage(values) == expected

    @pytest.mark.parametrize(
        "values",
        [
            {"breach_result": BREACH},
            {"breach_result": BREACH, "materiality": "below_mta"},
            {"breach_result": BREACH, "approval_decision": "rejected"},
            {"breach_result": BREACH, "notification_sent_at": SHOCK_DAY},
            {"breach_result": BREACH, "notification_sent_at": SHOCK_DAY, "sla_outcome": "met"},
            {
                "breach_result": BREACH,
                "approval_decision": "approved",
                "counterparty_tier": CounterpartyTier.ELITE,
            },
        ],
    )
    def test_agrees_with_the_feed_status(self, values) -> None:
        """open_call_stage and the feed's lifecycle status must not drift."""
        status = _lifecycle_status(values).value
        stage = open_call_stage(values)
        assert (stage is not None) == (
            status in ("awaiting_approval", "awaiting_manager_approval", "awaiting_sla_response")
        )
        if stage is not None:
            assert stage == status


class TestCounterpartyLease:
    def test_a_held_lease_makes_a_second_trigger_wait(self, session_factory):
        with counterparty_lease(session_factory, "CP-1"):
            with pytest.raises(CounterpartyBusyError), counterparty_lease(session_factory, "CP-1"):
                pass  # pragma: no cover
            with counterparty_lease(session_factory, "CP-3"):
                pass  # other counterparties are unaffected

        with counterparty_lease(session_factory, "CP-1"):
            pass  # released on exit

    def test_released_even_when_the_dispatch_fails(self, session_factory):
        with pytest.raises(RuntimeError), counterparty_lease(session_factory, "CP-1"):
            raise RuntimeError("boom")

        with session_factory() as session:
            assert session.execute(select(ProcessedEventORM)).scalars().all() == []

    def test_an_expired_lease_is_taken_over(self, session_factory):
        with session_factory() as session:
            session.add(
                ProcessedEventORM(
                    event_id="cp-lease:CP-1",
                    processed_at=datetime.now(UTC) - LEASE_TTL - timedelta(seconds=1),
                )
            )
            session.commit()

        with counterparty_lease(session_factory, "CP-1"):
            pass

    def test_dispatch_holds_the_lease(self, graph, session_factory):
        with counterparty_lease(session_factory, "CP-3"), pytest.raises(CounterpartyBusyError):
            dispatch_trigger(graph, _nvda_shock(), "CP-3", session_factory)


class TestFeedAndTrace:
    def test_held_breaches_are_not_calls_in_the_feed_or_history(self, graph, session_factory):
        from api.margin_calls import counterparty_history

        hpe = ImpactSet(
            event_id="HPE:2026-10-02:price_shock",
            event_type=MarketEventType.PRICE_SHOCK,
            counterparty_ids=["CP-3"],
            reason="HPE moved 7.4% vs prior close",
            occurred_at=datetime.now(UTC),
            price_moves=[PriceMove(ticker="HPE", from_price=65.07, to_price=69.88)],
        )
        handle_impact(hpe, session_factory, lambda: graph)

        (call,) = _calls(graph, session_factory)
        assert call.status is MarginCallLifecycleStatus.BELOW_MATERIALITY
        assert call.call_amount is None
        with session_factory() as session:
            history = counterparty_history(
                graph, session, "CP-3", settings=Settings(_env_file=None)
            )
        assert history is not None
        assert (history.total_calls, history.breached_calls) == (1, 0)

    def test_trace_shows_the_gate_and_the_reevaluation(self, graph, session_factory, feed):
        from api.margin_call_trace import get_margin_call_trace

        hpe = ImpactSet(
            event_id="HPE:2026-10-02:price_shock",
            event_type=MarketEventType.PRICE_SHOCK,
            counterparty_ids=["CP-3"],
            reason="HPE moved 7.4% vs prior close",
            occurred_at=SHOCK_DAY,
            price_moves=[PriceMove(ticker="HPE", from_price=65.07, to_price=69.88)],
        )
        (held,) = handle_impact(hpe, session_factory, lambda: graph)
        _daily_run(graph, session_factory)
        feed.prices["NVDA"] = 198.0
        handle_impact(_nvda_shock(), session_factory, lambda: graph)

        held_trace = get_margin_call_trace(graph, held.thread_id)
        updated_trace = get_margin_call_trace(graph, "daily-margin-run:2026-10-02:CP-3")

        assert held_trace is not None and updated_trace is not None
        assert any(
            s.summary.startswith(
                "Below materiality -- no intraday call (event moved exposure 1,366"
            )
            for s in held_trace.steps
        )
        summaries = [s.summary for s in updated_trace.steps]
        assert any(s.startswith("Re-evaluated: NVDA moved") for s in summaries)
        assert updated_trace.steps[-1].node == "Await human approval"
