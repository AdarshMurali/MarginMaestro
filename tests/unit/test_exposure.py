from datetime import UTC, date, datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from agents.csa_rag import CSATermsUnavailableError
from api.exposure import (
    _cached_csa_terms,
    build_exposure_board,
    get_price_history,
)
from api.schemas import ExposureStatus
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
from streaming.market_feed import MarketDataUnavailableError, PriceHistoryPoint, PriceQuote


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


@pytest.fixture(autouse=True)
def _clear_csa_terms_cache():
    _cached_csa_terms.cache_clear()
    yield
    _cached_csa_terms.cache_clear()


def _seed_counterparty(session_factory, counterparty_id: str, name: str | None = None) -> None:
    with session_factory() as session:
        session.add(
            CounterpartyORM(
                id=counterparty_id, name=name or counterparty_id, type="Bank", country="US"
            )
        )
        session.add(
            PortfolioORM(
                id=f"PF-{counterparty_id}", counterparty_id=counterparty_id, currency="USD"
            )
        )
        session.commit()


def _seed_position(
    session_factory, counterparty_id: str, ticker: str, quantity: float, prior_close: float
) -> None:
    with session_factory() as session:
        session.add(
            PositionORM(
                id=f"POS-{counterparty_id}-{ticker}",
                portfolio_id=f"PF-{counterparty_id}",
                ticker=ticker,
                asset_class="equity",
                quantity=quantity,
                trade_date=date(2026, 1, 1),
            )
        )
        session.add(
            PriceHistoryORM(
                ticker=ticker,
                price_date=date(2026, 1, 1),
                price=prior_close,
                currency="USD",
                source="test",
            )
        )
        session.commit()


def _seed_collateral(
    session_factory, counterparty_id: str, value_usd: float, haircut_pct: float = 0.0
) -> None:
    with session_factory() as session:
        session.add(
            CollateralItemORM(
                id=f"COLL-{counterparty_id}",
                counterparty_id=counterparty_id,
                collateral_type="cash",
                value_usd=value_usd,
                haircut_pct=haircut_pct,
            )
        )
        session.commit()


def _seed_vix(session_factory, value: float = 20.0) -> None:
    with session_factory() as session:
        session.add(ReferenceRateORM(series_id="VIXCLS", rate_date=date(2026, 1, 1), value=value))
        session.commit()


def _csa_result(counterparty_id: str, threshold: float, mta: float = 10_000.0) -> CSATermsResult:
    return CSATermsResult(
        counterparty_id=counterparty_id,
        threshold=threshold,
        mta=mta,
        currency="USD",
        eligible_collateral=["cash"],
        haircuts={"cash": 0.0},
        rating_triggers=[],
        citations=[],
    )


def _market_feed(prices: dict[str, float]) -> MagicMock:
    feed = MagicMock()
    now = datetime.now(UTC)
    feed.get_prices.return_value = {
        ticker: PriceQuote(ticker=ticker, price=price, as_of=now, source="test")
        for ticker, price in prices.items()
    }
    return feed


class TestCounterpartyExposureViaBoard:
    def test_no_positions_is_unavailable(self, session_factory) -> None:
        _seed_counterparty(session_factory, "CP-1")

        with session_factory() as session:
            result = build_exposure_board(session, _market_feed({}))

        item = result.counterparties[0]
        assert item.status == ExposureStatus.UNAVAILABLE
        assert "No positions" in item.detail
        assert item.positions == []

    def test_no_prior_close_is_unavailable_but_shows_positions(self, session_factory) -> None:
        _seed_counterparty(session_factory, "CP-1")
        with session_factory() as session:
            session.add(
                PositionORM(
                    id="POS-CP-1-AAPL",
                    portfolio_id="PF-CP-1",
                    ticker="AAPL",
                    asset_class="equity",
                    quantity=10,
                    trade_date=date(2026, 1, 1),
                )
            )
            session.commit()

        with session_factory() as session:
            result = build_exposure_board(session, _market_feed({"AAPL": 200.0}))

        item = result.counterparties[0]
        assert item.status == ExposureStatus.UNAVAILABLE
        assert "prior-day close" in item.detail
        assert item.positions[0].ticker == "AAPL"
        assert item.positions[0].price == 200.0

    def test_market_data_unavailable_is_unavailable(self, session_factory) -> None:
        _seed_counterparty(session_factory, "CP-1")
        _seed_position(session_factory, "CP-1", "AAPL", 10, prior_close=190.0)

        feed = MagicMock()
        feed.get_prices.side_effect = MarketDataUnavailableError("AAPL")
        with session_factory() as session:
            result = build_exposure_board(session, feed)

        assert result.counterparties[0].status == ExposureStatus.UNAVAILABLE

    def test_csa_terms_unavailable_is_unavailable_but_shows_positions(
        self, session_factory
    ) -> None:
        _seed_counterparty(session_factory, "CP-1")
        _seed_position(session_factory, "CP-1", "AAPL", 10, prior_close=190.0)
        _seed_vix(session_factory)

        with (
            patch("api.exposure.answer_csa_terms", side_effect=CSATermsUnavailableError("CP-1")),
            session_factory() as session,
        ):
            result = build_exposure_board(session, _market_feed({"AAPL": 200.0}))

        item = result.counterparties[0]
        assert item.status == ExposureStatus.UNAVAILABLE
        assert len(item.positions) == 1

    def test_healthy_status_when_exposure_well_below_threshold(self, session_factory) -> None:
        _seed_counterparty(session_factory, "CP-1")
        _seed_position(session_factory, "CP-1", "AAPL", 10, prior_close=200.0)
        _seed_vix(session_factory)

        with (
            patch(
                "api.exposure.answer_csa_terms",
                return_value=_csa_result("CP-1", threshold=1_000_000.0),
            ),
            session_factory() as session,
        ):
            result = build_exposure_board(session, _market_feed({"AAPL": 201.0}))

        assert result.counterparties[0].status == ExposureStatus.HEALTHY

    def test_at_risk_status_when_exposure_near_threshold_but_not_breached(
        self, session_factory
    ) -> None:
        # AAPL 10 shares: prior close 200 -> today 210 => VM = 100. IM at VIX
        # 20 (multiplier 1.0) on mtm_today=2100, equity risk weight 0.15 =>
        # 315. Exposure = 100 + 315 = 415. Threshold=500 -> 0.8*500=400, so
        # 415 clears the at-risk band; collateral covers any real shortfall
        # so it never actually breaches.
        _seed_counterparty(session_factory, "CP-1")
        _seed_position(session_factory, "CP-1", "AAPL", 10, prior_close=200.0)
        _seed_collateral(session_factory, "CP-1", value_usd=1_000_000.0)
        _seed_vix(session_factory)

        with (
            patch(
                "api.exposure.answer_csa_terms",
                return_value=_csa_result("CP-1", threshold=500.0, mta=1.0),
            ),
            session_factory() as session,
        ):
            result = build_exposure_board(session, _market_feed({"AAPL": 210.0}))

        item = result.counterparties[0]
        assert item.exposure == pytest.approx(415.0)
        assert item.status == ExposureStatus.AT_RISK

    def test_breached_status_when_shortfall_clears_mta(self, session_factory) -> None:
        _seed_counterparty(session_factory, "CP-1")
        _seed_position(session_factory, "CP-1", "AAPL", 10, prior_close=200.0)
        _seed_vix(session_factory)
        # No collateral seeded -- collateral_held is 0, so the full required
        # support becomes the call amount.

        with (
            patch(
                "api.exposure.answer_csa_terms",
                return_value=_csa_result("CP-1", threshold=100.0, mta=1.0),
            ),
            session_factory() as session,
        ):
            result = build_exposure_board(session, _market_feed({"AAPL": 210.0}))

        item = result.counterparties[0]
        assert item.status == ExposureStatus.BREACHED
        assert item.call_amount is not None and item.call_amount > 0

    def test_csa_terms_are_cached_across_counterparties_in_the_same_board(
        self, session_factory
    ) -> None:
        _seed_counterparty(session_factory, "CP-1")
        _seed_position(session_factory, "CP-1", "AAPL", 10, prior_close=200.0)
        _seed_vix(session_factory)

        with patch(
            "api.exposure.answer_csa_terms", return_value=_csa_result("CP-1", threshold=1_000_000.0)
        ) as mock_answer:
            with session_factory() as session:
                build_exposure_board(session, _market_feed({"AAPL": 201.0}))
            with session_factory() as session:
                build_exposure_board(session, _market_feed({"AAPL": 201.0}))

        mock_answer.assert_called_once()

    def test_board_lists_every_counterparty(self, session_factory) -> None:
        _seed_counterparty(session_factory, "CP-1")
        _seed_counterparty(session_factory, "CP-2")

        with session_factory() as session:
            result = build_exposure_board(session, _market_feed({}))

        assert {cp.counterparty_id for cp in result.counterparties} == {"CP-1", "CP-2"}


class TestGetPriceHistory:
    def test_wraps_market_feed_points_into_response(self) -> None:
        with patch(
            "api.exposure.fetch_ticker_price_history",
            return_value=[
                PriceHistoryPoint(date=date(2026, 1, 1), price=100.0),
                PriceHistoryPoint(date=date(2026, 1, 2), price=105.0),
            ],
        ) as mock_fetch:
            result = get_price_history("AAPL", days=10)

        mock_fetch.assert_called_once_with("AAPL", days=10)
        assert result.ticker == "AAPL"
        assert [p.price for p in result.points] == [100.0, 105.0]

    def test_propagates_market_data_unavailable(self) -> None:
        with (
            patch(
                "api.exposure.fetch_ticker_price_history",
                side_effect=MarketDataUnavailableError("BADTICKER"),
            ),
            pytest.raises(MarketDataUnavailableError),
        ):
            get_price_history("BADTICKER")
