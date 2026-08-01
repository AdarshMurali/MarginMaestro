from datetime import UTC, date, datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from agents.communication import NotificationResult
from agents.orchestrator import (
    MarginCallState,
    _collateral_held,
    _latest_vix,
    _load_positions,
    _route_after_approval,
    _route_after_breach,
    await_approval,
    await_sla_response,
    build_orchestrator_graph,
    compute_exposure,
    evaluate_breach_node,
    fetch_csa_terms,
    get_or_start_run,
    resume_run,
    send_notification,
    start_run,
    thread_id_for,
)
from calc.models import BreachResult, CSATerms, InitialMargin, PricingError, VariationMargin
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


def _seed_position(session_factory, counterparty_id: str, ticker: str, quantity: float) -> None:
    with session_factory() as session:
        session.add(
            CounterpartyORM(id=counterparty_id, name=counterparty_id, type="Bank", country="US")
        )
        portfolio_id = f"PF-{counterparty_id}"
        session.add(PortfolioORM(id=portfolio_id, counterparty_id=counterparty_id, currency="USD"))
        session.add(
            PositionORM(
                id=f"POS-{counterparty_id}-{ticker}",
                portfolio_id=portfolio_id,
                ticker=ticker,
                asset_class="equity",
                quantity=quantity,
                trade_date=date(2026, 1, 1),
            )
        )
        session.commit()


def _state(counterparty_id: str = "CP-1") -> MarginCallState:
    impact = ImpactSet(
        event_id="evt-1",
        event_type=MarketEventType.PRICE_SHOCK,
        counterparty_ids=[counterparty_id],
        reason="TSLA moved 12.0% vs prior close",
        occurred_at=datetime.now(UTC),
    )
    return MarginCallState(correlation_id="corr-1", impact=impact, counterparty_id=counterparty_id)


def _csa_result(counterparty_id: str = "CP-1", threshold: float = 100_000.0) -> CSATermsResult:
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


def _patch_draft_notice():
    return patch(
        "agents.orchestrator.draft_margin_call_notice", return_value="Mock margin call notice."
    )


def _patch_send_slack_notice():
    return patch(
        "agents.orchestrator.send_slack_notice",
        return_value=NotificationResult(
            notice_text="Mock margin call notice.",
            slack_channel="C0BMCAL6L74",
            slack_ts="123.456",
        ),
    )


class TestLoadPositions:
    def test_returns_positions_for_the_counterparty(self, session_factory) -> None:
        _seed_position(session_factory, "CP-1", "TSLA", 100)

        with session_factory() as session:
            positions = _load_positions(session, "CP-1")

        assert len(positions) == 1
        assert positions[0].ticker == "TSLA"

    def test_returns_empty_list_for_unknown_counterparty(self, session_factory) -> None:
        with session_factory() as session:
            assert _load_positions(session, "CP-404") == []


class TestLatestVix:
    def test_returns_most_recent_value(self, session_factory) -> None:
        with session_factory() as session:
            session.add_all(
                [
                    ReferenceRateORM(series_id="VIXCLS", rate_date=date(2026, 7, 29), value=18.0),
                    ReferenceRateORM(series_id="VIXCLS", rate_date=date(2026, 7, 30), value=22.0),
                ]
            )
            session.commit()

            assert _latest_vix(session) == 22.0

    def test_raises_when_no_vix_data(self, session_factory) -> None:
        with session_factory() as session, pytest.raises(PricingError):
            _latest_vix(session)


class TestCollateralHeld:
    def test_sums_value_net_of_haircut(self, session_factory) -> None:
        with session_factory() as session:
            session.add_all(
                [
                    CollateralItemORM(
                        id="C1",
                        counterparty_id="CP-1",
                        collateral_type="cash",
                        value_usd=100_000.0,
                        haircut_pct=0.0,
                    ),
                    CollateralItemORM(
                        id="C2",
                        counterparty_id="CP-1",
                        collateral_type="equity",
                        ticker="AAPL",
                        value_usd=50_000.0,
                        haircut_pct=0.1,
                    ),
                ]
            )
            session.commit()

            assert _collateral_held(session, "CP-1") == 100_000.0 + 45_000.0

    def test_zero_when_no_collateral(self, session_factory) -> None:
        with session_factory() as session:
            assert _collateral_held(session, "CP-1") == 0.0


class TestComputeExposure:
    def test_computes_mtm_vm_im_from_prior_close_and_live_price(self, session_factory) -> None:
        _seed_position(session_factory, "CP-1", "TSLA", 1000)
        with session_factory() as session:
            session.add(
                PriceHistoryORM(
                    ticker="TSLA",
                    price_date=date(2026, 7, 30),
                    price=100.0,
                    currency="USD",
                    source="yfinance",
                )
            )
            session.add(
                ReferenceRateORM(series_id="VIXCLS", rate_date=date(2026, 7, 30), value=20.0)
            )
            session.commit()

        market_feed = MagicMock()
        market_feed.get_prices.return_value = {
            "TSLA": PriceQuote(
                ticker="TSLA", price=120.0, as_of=datetime.now(UTC), source="yfinance"
            )
        }

        with session_factory() as session:
            result = compute_exposure(_state(), session, market_feed)

        assert result["portfolio_mtm"].total_mtm == 120_000.0
        assert result["variation_margin"].variation_margin == 20_000.0
        assert isinstance(result["initial_margin"], InitialMargin)
        assert result["initial_margin"].initial_margin > 0

    def test_raises_when_counterparty_has_no_positions(self, session_factory) -> None:
        market_feed = MagicMock()
        with session_factory() as session, pytest.raises(PricingError):
            compute_exposure(_state("CP-404"), session, market_feed)


class TestFetchCsaTerms:
    def test_maps_csa_terms_result_to_calc_csa_terms(self) -> None:
        with patch(
            "agents.orchestrator.answer_csa_terms", return_value=_csa_result(threshold=250_000.0)
        ) as mock_answer:
            result = fetch_csa_terms(_state(), Settings(_env_file=None))

        mock_answer.assert_called_once()
        assert result["csa_terms"] == CSATerms(threshold=250_000.0, mta=10_000.0, currency="USD")


class TestEvaluateBreachNode:
    def _state_with_vm_im(self, vm: float, im: float, threshold: float) -> MarginCallState:
        state = _state()
        state.variation_margin = VariationMargin(
            portfolio_id="PF-CP-1", mtm_today=0, mtm_prior=0, variation_margin=vm
        )
        state.initial_margin = InitialMargin(
            portfolio_id="PF-CP-1", vix_level=20.0, vix_multiplier=1.0, initial_margin=im
        )
        state.csa_terms = CSATerms(threshold=threshold, mta=1_000.0, currency="USD")
        return state

    def test_breaches_when_exposure_exceeds_threshold_and_mta(self, session_factory) -> None:
        state = self._state_with_vm_im(vm=100_000.0, im=10_000.0, threshold=1_000.0)

        with session_factory() as session:
            result = evaluate_breach_node(state, session)

        assert result["breach_result"].breached is True
        assert result["breach_result"].call_amount == pytest.approx(109_000.0)

    def test_no_breach_when_exposure_under_threshold(self, session_factory) -> None:
        state = self._state_with_vm_im(vm=0.0, im=5_000.0, threshold=1_000_000.0)

        with session_factory() as session:
            result = evaluate_breach_node(state, session)

        assert result["breach_result"].breached is False

    def test_raises_if_required_state_missing(self, session_factory) -> None:
        with session_factory() as session, pytest.raises(PricingError):
            evaluate_breach_node(_state(), session)


class TestRouteAfterBreach:
    def test_routes_to_await_approval_when_breached(self) -> None:
        state = _state()
        state.breach_result = BreachResult(breached=True, call_amount=1.0)
        assert _route_after_breach(state) == "await_approval"

    def test_routes_to_end_when_not_breached(self) -> None:
        state = _state()
        state.breach_result = BreachResult(breached=False, call_amount=0.0)
        assert _route_after_breach(state) != "await_approval"


class TestRouteAfterApproval:
    def test_routes_to_send_notification_when_approved(self) -> None:
        state = _state()
        state.approval_decision = "approved"
        assert _route_after_approval(state) == "send_notification"

    def test_routes_to_send_notification_when_adjusted(self) -> None:
        state = _state()
        state.approval_decision = "adjusted"
        assert _route_after_approval(state) == "send_notification"

    def test_routes_to_end_when_rejected(self) -> None:
        state = _state()
        state.approval_decision = "rejected"
        assert _route_after_approval(state) != "send_notification"


class TestSendNotification:
    def test_uses_adjusted_call_amount_when_decision_is_adjusted(self) -> None:
        state = _state()
        state.breach_result = BreachResult(breached=True, call_amount=474_000.0)
        state.csa_terms = CSATerms(threshold=1_000.0, mta=100.0, currency="USD")
        state.approval_decision = "adjusted"
        state.adjusted_call_amount = 42_000.0

        with _patch_draft_notice() as mock_draft, _patch_send_slack_notice():
            send_notification(state, Settings(_env_file=None))

        args, _ = mock_draft.call_args
        assert args[1] == 42_000.0

    def test_uses_breach_call_amount_when_decision_is_approved(self) -> None:
        state = _state()
        state.breach_result = BreachResult(breached=True, call_amount=474_000.0)
        state.csa_terms = CSATerms(threshold=1_000.0, mta=100.0, currency="USD")
        state.approval_decision = "approved"

        with _patch_draft_notice() as mock_draft, _patch_send_slack_notice():
            send_notification(state, Settings(_env_file=None))

        args, _ = mock_draft.call_args
        assert args[1] == 474_000.0

    def test_raises_if_breach_result_or_csa_terms_missing(self) -> None:
        with pytest.raises(PricingError):
            send_notification(_state(), Settings(_env_file=None))

    def test_records_notification_sent_at(self) -> None:
        state = _state()
        state.breach_result = BreachResult(breached=True, call_amount=474_000.0)
        state.csa_terms = CSATerms(threshold=1_000.0, mta=100.0, currency="USD")
        state.approval_decision = "approved"

        with _patch_draft_notice(), _patch_send_slack_notice():
            result = send_notification(state, Settings(_env_file=None))

        assert isinstance(result["notification_sent_at"], datetime)


class TestBuildOrchestratorGraph:
    def test_compiles(self, session_factory) -> None:
        graph = build_orchestrator_graph(
            session_factory=session_factory,
            market_feed=MagicMock(),
            settings=Settings(_env_file=None),
        )
        assert graph is not None

    def test_breach_scenario_runs_through_to_await_approval(self, session_factory) -> None:
        _seed_position(session_factory, "CP-1", "TSLA", 1000)
        with session_factory() as session:
            session.add(
                PriceHistoryORM(
                    ticker="TSLA",
                    price_date=date(2026, 7, 30),
                    price=100.0,
                    currency="USD",
                    source="yfinance",
                )
            )
            session.add(
                ReferenceRateORM(series_id="VIXCLS", rate_date=date(2026, 7, 30), value=20.0)
            )
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

        market_feed = MagicMock()
        market_feed.get_prices.return_value = {
            "TSLA": PriceQuote(
                ticker="TSLA", price=500.0, as_of=datetime.now(UTC), source="yfinance"
            )
        }

        with patch(
            "agents.orchestrator.answer_csa_terms", return_value=_csa_result(threshold=1_000.0)
        ):
            graph = build_orchestrator_graph(
                session_factory=session_factory,
                market_feed=market_feed,
                settings=Settings(_env_file=None),
            )
            result = start_run(graph, _state())

        assert result["breach_result"].breached is True
        assert "__interrupt__" in result  # paused at await_approval, not auto-approved

    def test_no_breach_scenario_ends_without_call(self, session_factory) -> None:
        _seed_position(session_factory, "CP-1", "TSLA", 100)
        with session_factory() as session:
            session.add(
                PriceHistoryORM(
                    ticker="TSLA",
                    price_date=date(2026, 7, 30),
                    price=100.0,
                    currency="USD",
                    source="yfinance",
                )
            )
            session.add(
                ReferenceRateORM(series_id="VIXCLS", rate_date=date(2026, 7, 30), value=20.0)
            )
            session.commit()

        market_feed = MagicMock()
        market_feed.get_prices.return_value = {
            "TSLA": PriceQuote(
                ticker="TSLA", price=100.0, as_of=datetime.now(UTC), source="yfinance"
            )
        }

        with patch(
            "agents.orchestrator.answer_csa_terms", return_value=_csa_result(threshold=1_000_000.0)
        ):
            graph = build_orchestrator_graph(
                session_factory=session_factory,
                market_feed=market_feed,
                settings=Settings(_env_file=None),
            )
            result = start_run(graph, _state())

        assert result["breach_result"].breached is False
        assert "__interrupt__" not in result  # no-breach ends the run outright

    def test_pause_then_resume_completes_the_run_with_the_approval_decision(
        self, session_factory
    ) -> None:
        _seed_position(session_factory, "CP-1", "TSLA", 1000)
        with session_factory() as session:
            session.add(
                PriceHistoryORM(
                    ticker="TSLA",
                    price_date=date(2026, 7, 30),
                    price=100.0,
                    currency="USD",
                    source="yfinance",
                )
            )
            session.add(
                ReferenceRateORM(series_id="VIXCLS", rate_date=date(2026, 7, 30), value=20.0)
            )
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

        market_feed = MagicMock()
        market_feed.get_prices.return_value = {
            "TSLA": PriceQuote(
                ticker="TSLA", price=500.0, as_of=datetime.now(UTC), source="yfinance"
            )
        }
        state = _state()

        with (
            patch(
                "agents.orchestrator.answer_csa_terms", return_value=_csa_result(threshold=1_000.0)
            ),
            _patch_draft_notice(),
            _patch_send_slack_notice(),
        ):
            graph = build_orchestrator_graph(
                session_factory=session_factory,
                market_feed=market_feed,
                settings=Settings(_env_file=None),
            )
            paused = start_run(graph, state)
            assert "__interrupt__" in paused

            thread_id = thread_id_for(state.impact, state.counterparty_id)
            approved = resume_run(graph, thread_id, {"decision": "approved"})
            assert "__interrupt__" in approved  # now paused at await_sla_response instead

            resumed = resume_run(graph, thread_id, {"responded": True})

        assert "__interrupt__" not in resumed
        assert resumed["approval_decision"] == "approved"
        assert resumed["adjusted_call_amount"] is None
        assert resumed["notification_result"].slack_channel == "C0BMCAL6L74"
        assert resumed["sla_outcome"] == "met"

    def test_resume_with_adjusted_decision_carries_the_adjusted_amount(
        self, session_factory
    ) -> None:
        _seed_position(session_factory, "CP-1", "TSLA", 1000)
        with session_factory() as session:
            session.add(
                PriceHistoryORM(
                    ticker="TSLA",
                    price_date=date(2026, 7, 30),
                    price=100.0,
                    currency="USD",
                    source="yfinance",
                )
            )
            session.add(
                ReferenceRateORM(series_id="VIXCLS", rate_date=date(2026, 7, 30), value=20.0)
            )
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

        market_feed = MagicMock()
        market_feed.get_prices.return_value = {
            "TSLA": PriceQuote(
                ticker="TSLA", price=500.0, as_of=datetime.now(UTC), source="yfinance"
            )
        }
        state = _state()

        with (
            patch(
                "agents.orchestrator.answer_csa_terms", return_value=_csa_result(threshold=1_000.0)
            ),
            _patch_draft_notice(),
            _patch_send_slack_notice(),
        ):
            graph = build_orchestrator_graph(
                session_factory=session_factory,
                market_feed=market_feed,
                settings=Settings(_env_file=None),
            )
            start_run(graph, state)
            resumed = resume_run(
                graph,
                thread_id_for(state.impact, state.counterparty_id),
                {"decision": "adjusted", "adjusted_call_amount": 42_000.0},
            )

        assert resumed["approval_decision"] == "adjusted"
        assert resumed["adjusted_call_amount"] == 42_000.0
        assert resumed["notification_result"].slack_channel == "C0BMCAL6L74"

    def test_resume_with_rejected_decision_completes_the_run(self, session_factory) -> None:
        _seed_breach_scenario(session_factory)
        state = _state()

        with patch(
            "agents.orchestrator.answer_csa_terms", return_value=_csa_result(threshold=1_000.0)
        ):
            graph = build_orchestrator_graph(
                session_factory=session_factory,
                market_feed=_breach_market_feed(),
                settings=Settings(_env_file=None),
            )
            start_run(graph, state)
            resumed = resume_run(
                graph,
                thread_id_for(state.impact, state.counterparty_id),
                {"decision": "rejected"},
            )

        assert "__interrupt__" not in resumed
        assert resumed["approval_decision"] == "rejected"
        assert resumed["adjusted_call_amount"] is None


def _seed_breach_scenario(session_factory) -> None:
    _seed_position(session_factory, "CP-1", "TSLA", 1000)
    with session_factory() as session:
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


def _breach_market_feed() -> MagicMock:
    market_feed = MagicMock()
    market_feed.get_prices.return_value = {
        "TSLA": PriceQuote(ticker="TSLA", price=500.0, as_of=datetime.now(UTC), source="yfinance")
    }
    return market_feed


class TestRestartSurvival:
    """MM-38's actual point: a paused run must survive the orchestrator
    process restarting, not just resuming within the same graph object."""

    def test_a_freshly_built_graph_resumes_a_run_paused_by_a_different_graph_object(
        self, session_factory
    ) -> None:
        _seed_breach_scenario(session_factory)
        state = _state()

        with (
            patch(
                "agents.orchestrator.answer_csa_terms", return_value=_csa_result(threshold=1_000.0)
            ),
            _patch_draft_notice(),
            _patch_send_slack_notice(),
        ):
            graph1 = build_orchestrator_graph(
                session_factory=session_factory,
                market_feed=_breach_market_feed(),
                settings=Settings(_env_file=None),
            )
            paused = start_run(graph1, state)
            assert "__interrupt__" in paused

            # Simulate a process restart: a brand new graph/checkpointer, same DB.
            graph2 = build_orchestrator_graph(
                session_factory=session_factory,
                market_feed=_breach_market_feed(),
                settings=Settings(_env_file=None),
            )
            resumed = resume_run(
                graph2,
                thread_id_for(state.impact, state.counterparty_id),
                {"decision": "approved"},
            )

        # Now paused at await_sla_response instead of finished -- still proves
        # the restart-survival point: graph2 correctly picked up where graph1
        # left off and advanced to the next step.
        assert "__interrupt__" in resumed
        assert resumed["approval_decision"] == "approved"


class TestSlaTimer:
    def _resume_to_sla_pause(self, session_factory, settings: Settings) -> tuple:
        _seed_breach_scenario(session_factory)
        state = _state()

        with (
            patch(
                "agents.orchestrator.answer_csa_terms", return_value=_csa_result(threshold=1_000.0)
            ),
            _patch_draft_notice(),
            _patch_send_slack_notice(),
        ):
            graph = build_orchestrator_graph(
                session_factory=session_factory,
                market_feed=_breach_market_feed(),
                settings=settings,
            )
            thread_id = thread_id_for(state.impact, state.counterparty_id)
            start_run(graph, state)
            paused_at_sla = resume_run(graph, thread_id, {"decision": "approved"})
        return graph, thread_id, paused_at_sla

    def test_stays_pending_before_the_deadline_when_checked(self, session_factory) -> None:
        graph, thread_id, paused_at_sla = self._resume_to_sla_pause(
            session_factory, Settings(_env_file=None, margin_call_sla_minutes=60)
        )
        assert "__interrupt__" in paused_at_sla

        still_pending = resume_run(graph, thread_id, {"check": True})

        assert "__interrupt__" in still_pending
        assert "sla_outcome" not in still_pending

    def test_resolves_breached_once_the_deadline_has_passed(self, session_factory) -> None:
        graph, thread_id, paused_at_sla = self._resume_to_sla_pause(
            session_factory, Settings(_env_file=None, margin_call_sla_minutes=0)
        )
        assert "__interrupt__" in paused_at_sla

        resolved = resume_run(graph, thread_id, {"check": True})

        assert "__interrupt__" not in resolved
        assert resolved["sla_outcome"] == "breached"

    def test_resolves_met_when_responded_before_the_deadline(self, session_factory) -> None:
        graph, thread_id, paused_at_sla = self._resume_to_sla_pause(
            session_factory, Settings(_env_file=None, margin_call_sla_minutes=60)
        )
        assert "__interrupt__" in paused_at_sla

        resolved = resume_run(graph, thread_id, {"responded": True})

        assert "__interrupt__" not in resolved
        assert resolved["sla_outcome"] == "met"


class TestGetOrStartRun:
    def test_starts_a_new_run_when_none_exists(self, session_factory) -> None:
        _seed_breach_scenario(session_factory)
        market_feed = _breach_market_feed()
        state = _state()

        with patch(
            "agents.orchestrator.answer_csa_terms", return_value=_csa_result(threshold=1_000.0)
        ):
            graph = build_orchestrator_graph(
                session_factory=session_factory,
                market_feed=market_feed,
                settings=Settings(_env_file=None),
            )
            result = get_or_start_run(graph, state)

        assert "__interrupt__" in result
        market_feed.get_prices.assert_called_once()

    def test_replaying_the_same_run_does_not_recompute_exposure(self, session_factory) -> None:
        """CLAUDE.md's idempotency rule: replaying the same event must not
        double-raise a call. Re-dispatching the same (event_id,
        counterparty_id) must not re-invoke the calc pipeline."""
        _seed_breach_scenario(session_factory)
        market_feed = _breach_market_feed()
        state = _state()

        with patch(
            "agents.orchestrator.answer_csa_terms", return_value=_csa_result(threshold=1_000.0)
        ):
            graph = build_orchestrator_graph(
                session_factory=session_factory,
                market_feed=market_feed,
                settings=Settings(_env_file=None),
            )
            first = get_or_start_run(graph, state)
            second = get_or_start_run(graph, state)

        assert "__interrupt__" in first
        assert "__interrupt__" in second
        market_feed.get_prices.assert_called_once()


class TestMarginCallState:
    def test_correlation_id_is_auto_generated_when_not_provided(self) -> None:
        impact = ImpactSet(
            event_id="evt-x",
            event_type=MarketEventType.PRICE_SHOCK,
            counterparty_ids=["CP-1"],
            reason="test",
            occurred_at=datetime.now(UTC),
        )
        state_a = MarginCallState(impact=impact, counterparty_id="CP-1")
        state_b = MarginCallState(impact=impact, counterparty_id="CP-1")

        assert state_a.correlation_id
        assert state_a.correlation_id != state_b.correlation_id


class TestAwaitApproval:
    def test_raises_if_breach_result_missing(self) -> None:
        with pytest.raises(PricingError):
            await_approval(_state())


class TestAwaitSlaResponse:
    def test_raises_if_notification_sent_at_missing(self) -> None:
        with pytest.raises(PricingError):
            await_sla_response(_state(), Settings(_env_file=None))


class TestThreadIdFor:
    def test_combines_event_id_and_counterparty_id(self) -> None:
        state = _state("CP-7")
        assert thread_id_for(state.impact, state.counterparty_id) == "evt-1:CP-7"
