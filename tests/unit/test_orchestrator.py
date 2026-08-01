from datetime import UTC, date, datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from agents.orchestrator import (
    MarginCallState,
    _collateral_held,
    _latest_vix,
    _load_positions,
    _route_after_breach,
    await_approval,
    build_orchestrator_graph,
    compute_exposure,
    evaluate_breach_node,
    fetch_csa_terms,
    resume_run,
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

        with patch(
            "agents.orchestrator.answer_csa_terms", return_value=_csa_result(threshold=1_000.0)
        ):
            graph = build_orchestrator_graph(
                session_factory=session_factory,
                market_feed=market_feed,
                settings=Settings(_env_file=None),
            )
            paused = start_run(graph, state)
            assert "__interrupt__" in paused

            resumed = resume_run(
                graph, thread_id_for(state.impact, state.counterparty_id), {"decision": "approved"}
            )

        assert "__interrupt__" not in resumed
        assert resumed["approval_decision"] == "approved"
        assert resumed["adjusted_call_amount"] is None

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

        with patch(
            "agents.orchestrator.answer_csa_terms", return_value=_csa_result(threshold=1_000.0)
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


class TestAwaitApproval:
    def test_raises_if_breach_result_missing(self) -> None:
        with pytest.raises(PricingError):
            await_approval(_state())


class TestThreadIdFor:
    def test_combines_event_id_and_counterparty_id(self) -> None:
        state = _state("CP-7")
        assert thread_id_for(state.impact, state.counterparty_id) == "evt-1:CP-7"
