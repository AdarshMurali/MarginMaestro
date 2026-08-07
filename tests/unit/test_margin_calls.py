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
from api.margin_calls import (
    _lifecycle_status,
    list_margin_call_buckets,
    list_margin_calls,
    list_margin_calls_for_counterparty,
)
from api.schemas import MarginCallLifecycleStatus, MarginCallSummary
from config.settings import Settings
from persistence.db.models import (
    Base,
    CheckpointORM,
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


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _seed_scenario(session_factory, counterparty_id: str, prior_price: float = 100.0) -> None:
    with session_factory() as session:
        session.add(
            CounterpartyORM(id=counterparty_id, name=counterparty_id, type="Bank", country="US")
        )
        portfolio_id = f"PF-{counterparty_id}"
        session.add(PortfolioORM(id=portfolio_id, counterparty_id=counterparty_id, currency="USD"))
        session.add(
            PositionORM(
                id=f"POS-{counterparty_id}",
                portfolio_id=portfolio_id,
                ticker="TSLA",
                asset_class="equity",
                quantity=1000,
                trade_date=date(2026, 1, 1),
            )
        )
        # merge, not add: TSLA's prior close is shared market data, not
        # per-counterparty -- multiple scenarios legitimately reference the
        # same (ticker, price_date) row rather than each needing their own.
        session.merge(
            PriceHistoryORM(
                ticker="TSLA",
                price_date=date(2026, 7, 30),
                price=prior_price,
                currency="USD",
                source="test",
            )
        )
        session.merge(ReferenceRateORM(series_id="VIXCLS", rate_date=date(2026, 7, 30), value=20.0))
        session.add(
            CollateralItemORM(
                id=f"COLL-{counterparty_id}",
                counterparty_id=counterparty_id,
                collateral_type="cash",
                value_usd=0.0,
                haircut_pct=0.0,
            )
        )
        session.commit()


def _seed_counterparty(session_factory, counterparty_id: str, name: str) -> None:
    with session_factory() as session:
        session.add(CounterpartyORM(id=counterparty_id, name=name, type="Bank", country="US"))
        session.commit()


def _summary(
    counterparty_id: str,
    thread_id: str,
    status: MarginCallLifecycleStatus,
    occurred_at: datetime,
) -> MarginCallSummary:
    return MarginCallSummary(
        thread_id=thread_id,
        correlation_id=f"corr-{thread_id}",
        counterparty_id=counterparty_id,
        event_type="price_shock",
        reason="test",
        occurred_at=occurred_at,
        status=status,
    )


def _state(event_id: str, counterparty_id: str) -> MarginCallState:
    impact = ImpactSet(
        event_id=event_id,
        event_type=MarketEventType.PRICE_SHOCK,
        counterparty_ids=[counterparty_id],
        reason="TSLA moved 400% vs prior close",
        occurred_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    return MarginCallState(
        correlation_id=f"corr-{event_id}", impact=impact, counterparty_id=counterparty_id
    )


def _csa_result(counterparty_id: str, threshold: float) -> CSATermsResult:
    return CSATermsResult(
        counterparty_id=counterparty_id,
        threshold=threshold,
        mta=10_000.0,
        currency="USD",
        eligible_collateral=["cash"],
        haircuts={"cash": 0.0},
        rating_triggers=[],
        citations=[],
    )


def _breach_market_feed() -> MagicMock:
    feed = MagicMock()
    feed.get_prices.return_value = {
        "TSLA": PriceQuote(ticker="TSLA", price=500.0, as_of=datetime.now(UTC), source="test")
    }
    return feed


def _no_breach_market_feed() -> MagicMock:
    feed = MagicMock()
    feed.get_prices.return_value = {
        "TSLA": PriceQuote(ticker="TSLA", price=100.0, as_of=datetime.now(UTC), source="test")
    }
    return feed


def _patch_notify():
    return (
        patch("agents.orchestrator.draft_margin_call_notice", return_value="Mock notice."),
        patch(
            "agents.orchestrator.send_slack_notice",
            return_value=NotificationResult(
                notice_text="Mock notice.", slack_channel="C0BMCAL6L74", slack_ts="123.456"
            ),
        ),
    )


class TestLifecycleStatus:
    def test_evaluating_when_nothing_computed_yet(self) -> None:
        assert _lifecycle_status({}) == MarginCallLifecycleStatus.EVALUATING

    def test_defensive_escalated_fallback_when_sla_breached_without_escalation_result(self) -> None:
        # escalate() always runs synchronously right after sla_outcome
        # resolves "breached" in the real graph, so this combination isn't
        # reachable through the orchestrator today -- still worth locking
        # down that a future ordering change wouldn't silently misreport a
        # breach as some other status.
        assert (
            _lifecycle_status({"sla_outcome": "breached", "escalation_result": None})
            == MarginCallLifecycleStatus.ESCALATED
        )


class TestListMarginCalls:
    def test_empty_when_no_runs_exist(self, session_factory) -> None:
        graph = build_orchestrator_graph(
            session_factory=session_factory,
            market_feed=MagicMock(),
            settings=Settings(_env_file=None),
        )
        with session_factory() as session:
            result = list_margin_calls(graph, session)

        assert result.margin_calls == []

    def test_skips_a_thread_whose_state_snapshot_is_empty(self, session_factory) -> None:
        # Defensive branch: thread_ids come from the checkpoint table, so an
        # empty snapshot shouldn't happen in practice -- mock the graph
        # directly to exercise it rather than trying to contrive real
        # checkpoint data that deserializes to nothing.
        with session_factory() as session:
            session.add(
                CheckpointORM(
                    thread_id="ghost-thread",
                    checkpoint_ns="",
                    checkpoint_id="1",
                    parent_checkpoint_id=None,
                    checkpoint_type="json",
                    checkpoint_blob=b"{}",
                    metadata_type="json",
                    metadata_blob=b"{}",
                    created_at=datetime.now(UTC),
                )
            )
            session.commit()

        fake_graph = MagicMock()
        fake_graph.get_state.return_value = MagicMock(values={})

        with session_factory() as session:
            result = list_margin_calls(fake_graph, session)

        assert result.margin_calls == []

    def test_reports_every_lifecycle_stage_across_distinct_runs(self, session_factory) -> None:
        _seed_scenario(session_factory, "CP-NOBREACH")
        _seed_scenario(session_factory, "CP-PENDING")
        _seed_scenario(session_factory, "CP-REJECTED")
        _seed_scenario(session_factory, "CP-MET")
        _seed_scenario(session_factory, "CP-ESCALATED")
        _seed_scenario(session_factory, "CP-AWAITINGSLA")
        _seed_scenario(session_factory, "CP-ADJUSTED")

        notify_patches = _patch_notify()
        with (
            patch("agents.orchestrator.answer_csa_terms") as mock_csa,
            notify_patches[0],
            notify_patches[1],
        ):

            def _csa_side_effect(counterparty_id, **_):
                # CP-NOBREACH needs a threshold above IM alone (~15% of
                # notional even at zero VM), not just above VM -- a tiny
                # threshold breaches on IM alone regardless of price move.
                threshold = 1_000_000.0 if counterparty_id == "CP-NOBREACH" else 1_000.0
                return _csa_result(counterparty_id, threshold)

            mock_csa.side_effect = _csa_side_effect

            graph = build_orchestrator_graph(
                session_factory=session_factory,
                market_feed=_no_breach_market_feed(),
                settings=Settings(_env_file=None),
            )
            start_run(graph, _state("evt-nobreach", "CP-NOBREACH"))

            graph = build_orchestrator_graph(
                session_factory=session_factory,
                market_feed=_breach_market_feed(),
                settings=Settings(_env_file=None),
            )
            start_run(graph, _state("evt-pending", "CP-PENDING"))

            start_run(graph, _state("evt-rejected", "CP-REJECTED"))
            resume_run(
                graph,
                thread_id_for(_state("evt-rejected", "CP-REJECTED").impact, "CP-REJECTED"),
                {"decision": "rejected"},
            )

            met_state = _state("evt-met", "CP-MET")
            start_run(graph, met_state)
            resume_run(graph, thread_id_for(met_state.impact, "CP-MET"), {"decision": "approved"})
            resume_run(graph, thread_id_for(met_state.impact, "CP-MET"), {"responded": True})

            awaiting_state = _state("evt-awaitingsla", "CP-AWAITINGSLA")
            start_run(graph, awaiting_state)
            resume_run(
                graph,
                thread_id_for(awaiting_state.impact, "CP-AWAITINGSLA"),
                {"decision": "approved"},
            )

            adjusted_state = _state("evt-adjusted", "CP-ADJUSTED")
            start_run(graph, adjusted_state)
            resume_run(
                graph,
                thread_id_for(adjusted_state.impact, "CP-ADJUSTED"),
                {"decision": "adjusted", "adjusted_call_amount": 42_000.0},
            )

            esc_state = _state("evt-escalated", "CP-ESCALATED")
            sla_zero_graph = build_orchestrator_graph(
                session_factory=session_factory,
                market_feed=_breach_market_feed(),
                settings=Settings(_env_file=None, margin_call_sla_minutes=0),
            )
            start_run(sla_zero_graph, esc_state)
            resume_run(
                sla_zero_graph,
                thread_id_for(esc_state.impact, "CP-ESCALATED"),
                {"decision": "approved"},
            )
            with (
                patch(
                    "agents.orchestrator.retrieve_escalation_procedure",
                    return_value="[Escalation Trigger]\nMock procedure.",
                ),
                patch(
                    "agents.orchestrator.open_servicenow_incident",
                    return_value=IncidentResult(
                        incident_number="INC0010001", sys_id="abc123", urgency="2"
                    ),
                ),
            ):
                resume_run(
                    sla_zero_graph, thread_id_for(esc_state.impact, "CP-ESCALATED"), {"check": True}
                )

        with session_factory() as session:
            result = list_margin_calls(graph, session)

        by_counterparty = {item.counterparty_id: item for item in result.margin_calls}
        assert set(by_counterparty) == {
            "CP-NOBREACH",
            "CP-PENDING",
            "CP-REJECTED",
            "CP-MET",
            "CP-ESCALATED",
            "CP-AWAITINGSLA",
            "CP-ADJUSTED",
        }
        # Found live (MM-55): call_amount must reflect the *adjusted* figure
        # once approval_decision is "adjusted", not the original breach
        # amount that's no longer what was actually called for.
        assert by_counterparty["CP-ADJUSTED"].approval_decision == "adjusted"
        assert by_counterparty["CP-ADJUSTED"].call_amount == pytest.approx(42_000.0)
        awaiting = by_counterparty["CP-AWAITINGSLA"]
        assert awaiting.status == MarginCallLifecycleStatus.AWAITING_SLA_RESPONSE
        assert awaiting.notification_sent_at is not None
        # Settings(_env_file=None) defaults margin_call_sla_minutes to 60.
        assert awaiting.sla_deadline == awaiting.notification_sent_at + timedelta(minutes=60)
        assert by_counterparty["CP-MET"].sla_deadline is not None
        assert by_counterparty["CP-PENDING"].sla_deadline is None
        assert by_counterparty["CP-NOBREACH"].status == MarginCallLifecycleStatus.NO_BREACH
        # evaluate_breach always returns a BreachResult, even when not
        # breached -- call_amount is a real 0.0, not None (None means "no
        # breach_result at all", a state this thread never actually has).
        assert by_counterparty["CP-NOBREACH"].call_amount == 0.0
        assert by_counterparty["CP-PENDING"].status == MarginCallLifecycleStatus.AWAITING_APPROVAL
        assert by_counterparty["CP-PENDING"].call_amount == pytest.approx(474_000.0)
        assert by_counterparty["CP-REJECTED"].status == MarginCallLifecycleStatus.REJECTED
        assert by_counterparty["CP-MET"].status == MarginCallLifecycleStatus.SLA_MET
        assert by_counterparty["CP-ESCALATED"].status == MarginCallLifecycleStatus.ESCALATED
        assert result.margin_calls[0].event_type == "price_shock"
        assert result.margin_calls[0].reason == "TSLA moved 400% vs prior close"


class TestListMarginCallsForCounterparty:
    def test_filters_to_just_the_requested_counterparty(self, session_factory) -> None:
        calls = [
            _summary(
                "CP-1",
                "t1",
                MarginCallLifecycleStatus.AWAITING_APPROVAL,
                datetime(2026, 8, 1, tzinfo=UTC),
            ),
            _summary(
                "CP-2", "t2", MarginCallLifecycleStatus.NO_BREACH, datetime(2026, 8, 1, tzinfo=UTC)
            ),
            _summary(
                "CP-1", "t3", MarginCallLifecycleStatus.NO_BREACH, datetime(2026, 7, 30, tzinfo=UTC)
            ),
        ]
        with (
            patch("api.margin_calls._all_summaries", return_value=calls),
            session_factory() as session,
        ):
            result = list_margin_calls_for_counterparty(MagicMock(), session, "CP-1")

        assert [c.thread_id for c in result.margin_calls] == ["t1", "t3"]

    def test_empty_for_a_counterparty_with_no_calls(self, session_factory) -> None:
        with (
            patch("api.margin_calls._all_summaries", return_value=[]),
            session_factory() as session,
        ):
            result = list_margin_calls_for_counterparty(MagicMock(), session, "CP-NONE")

        assert result.margin_calls == []


class TestListMarginCallBuckets:
    def test_one_bucket_per_counterparty_with_resolved_names(self, session_factory) -> None:
        _seed_counterparty(session_factory, "CP-1", "Alpha")
        _seed_counterparty(session_factory, "CP-2", "Beta")
        calls = [
            _summary(
                "CP-1", "t1", MarginCallLifecycleStatus.NO_BREACH, datetime(2026, 8, 1, tzinfo=UTC)
            ),
            _summary(
                "CP-2", "t2", MarginCallLifecycleStatus.NO_BREACH, datetime(2026, 8, 1, tzinfo=UTC)
            ),
        ]
        with (
            patch("api.margin_calls._all_summaries", return_value=calls),
            session_factory() as session,
        ):
            result = list_margin_call_buckets(MagicMock(), session)

        assert {b.counterparty_id for b in result.buckets} == {"CP-1", "CP-2"}
        assert {b.counterparty_name for b in result.buckets} == {"Alpha", "Beta"}
        assert all(b.total_count == 1 for b in result.buckets)

    def test_picks_the_most_urgent_call_not_just_the_latest(self, session_factory) -> None:
        _seed_counterparty(session_factory, "CP-1", "Alpha")
        # Most recent call is resolved (NO_BREACH); an OLDER call is still
        # awaiting approval -- the older, more urgent one must win, not the
        # newer resolved one that would otherwise silently bury it.
        calls = [
            _summary(
                "CP-1",
                "t-new-resolved",
                MarginCallLifecycleStatus.NO_BREACH,
                datetime(2026, 8, 2, tzinfo=UTC),
            ),
            _summary(
                "CP-1",
                "t-old-urgent",
                MarginCallLifecycleStatus.AWAITING_APPROVAL,
                datetime(2026, 8, 1, tzinfo=UTC),
            ),
        ]
        with (
            patch("api.margin_calls._all_summaries", return_value=calls),
            session_factory() as session,
        ):
            result = list_margin_call_buckets(MagicMock(), session)

        bucket = result.buckets[0]
        assert bucket.latest.thread_id == "t-old-urgent"
        assert bucket.total_count == 2

    def test_ties_in_urgency_break_by_recency(self, session_factory) -> None:
        _seed_counterparty(session_factory, "CP-1", "Alpha")
        earlier = _summary(
            "CP-1",
            "t-earlier",
            MarginCallLifecycleStatus.AWAITING_APPROVAL,
            datetime(2026, 8, 1, tzinfo=UTC),
        )
        later = _summary(
            "CP-1",
            "t-later",
            MarginCallLifecycleStatus.AWAITING_APPROVAL,
            datetime(2026, 8, 2, tzinfo=UTC),
        )
        # _all_summaries always returns most-recent-first in practice -- the
        # tie-break relies on that ordering, so mirror it here.
        with (
            patch("api.margin_calls._all_summaries", return_value=[later, earlier]),
            session_factory() as session,
        ):
            result = list_margin_call_buckets(MagicMock(), session)

        assert result.buckets[0].latest.thread_id == "t-later"

    def test_buckets_are_sorted_urgency_first(self, session_factory) -> None:
        _seed_counterparty(session_factory, "CP-RESOLVED", "Resolved Co")
        _seed_counterparty(session_factory, "CP-URGENT", "Urgent Co")
        calls = [
            _summary(
                "CP-RESOLVED",
                "t1",
                MarginCallLifecycleStatus.NO_BREACH,
                datetime(2026, 8, 2, tzinfo=UTC),
            ),
            _summary(
                "CP-URGENT",
                "t2",
                MarginCallLifecycleStatus.AWAITING_APPROVAL,
                datetime(2026, 8, 1, tzinfo=UTC),
            ),
        ]
        with (
            patch("api.margin_calls._all_summaries", return_value=calls),
            session_factory() as session,
        ):
            result = list_margin_call_buckets(MagicMock(), session)

        assert [b.counterparty_id for b in result.buckets] == ["CP-URGENT", "CP-RESOLVED"]

    def test_falls_back_to_counterparty_id_if_name_unknown(self, session_factory) -> None:
        # No CounterpartyORM seeded for CP-GHOST.
        calls = [
            _summary(
                "CP-GHOST",
                "t1",
                MarginCallLifecycleStatus.NO_BREACH,
                datetime(2026, 8, 1, tzinfo=UTC),
            )
        ]
        with (
            patch("api.margin_calls._all_summaries", return_value=calls),
            session_factory() as session,
        ):
            result = list_margin_call_buckets(MagicMock(), session)

        assert result.buckets[0].counterparty_name == "CP-GHOST"

    def test_empty_when_no_calls_exist(self, session_factory) -> None:
        with (
            patch("api.margin_calls._all_summaries", return_value=[]),
            session_factory() as session,
        ):
            result = list_margin_call_buckets(MagicMock(), session)

        assert result.buckets == []
