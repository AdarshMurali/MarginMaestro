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
    get_counterparty_exposure,
    get_price_history,
    list_counterparty_summaries,
)
from api.schemas import ExposureStatus
from persistence.db.models import (
    Base,
    CollateralItemORM,
    CounterpartyORM,
    LatestPriceORM,
    PortfolioORM,
    PositionORM,
    PriceHistoryORM,
    ReferenceRateORM,
)
from persistence.models import PriceHistoryEntry
from rag.models import CSATermsResult
from streaming.market_feed import MarketDataUnavailableError


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


def _seed_latest_price(session_factory, ticker: str, price: float) -> None:
    now = datetime.now(UTC)
    with session_factory() as session:
        session.add(
            LatestPriceORM(
                ticker=ticker,
                price=price,
                currency="USD",
                source="test",
                as_of=now,
                updated_at=now,
            )
        )
        session.commit()


class TestCounterpartyExposureViaBoard:
    def test_no_positions_is_unavailable(self, session_factory) -> None:
        _seed_counterparty(session_factory, "CP-1")

        with session_factory() as session:
            result = build_exposure_board(session)

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
        _seed_latest_price(session_factory, "AAPL", 200.0)

        with session_factory() as session:
            result = build_exposure_board(session)

        item = result.counterparties[0]
        assert item.status == ExposureStatus.UNAVAILABLE
        assert "prior-day close" in item.detail
        assert item.positions[0].ticker == "AAPL"
        assert item.positions[0].price == 200.0

    def test_market_data_unavailable_is_unavailable(self, session_factory) -> None:
        _seed_counterparty(session_factory, "CP-1")
        _seed_position(session_factory, "CP-1", "AAPL", 10, prior_close=190.0)
        # No LatestPriceORM row seeded for AAPL -- compute_mtm raises
        # PricingError for the missing ticker, same as a real gap between
        # the poller starting and this ticker's first tick.

        with session_factory() as session:
            result = build_exposure_board(session)

        assert result.counterparties[0].status == ExposureStatus.UNAVAILABLE

    def test_csa_terms_unavailable_is_unavailable_but_shows_positions(
        self, session_factory
    ) -> None:
        _seed_counterparty(session_factory, "CP-1")
        _seed_position(session_factory, "CP-1", "AAPL", 10, prior_close=190.0)
        _seed_vix(session_factory)
        _seed_latest_price(session_factory, "AAPL", 200.0)

        with (
            patch("api.exposure.answer_csa_terms", side_effect=CSATermsUnavailableError("CP-1")),
            session_factory() as session,
        ):
            result = build_exposure_board(session)

        item = result.counterparties[0]
        assert item.status == ExposureStatus.UNAVAILABLE
        assert len(item.positions) == 1

    def test_healthy_status_when_exposure_well_below_threshold(self, session_factory) -> None:
        _seed_counterparty(session_factory, "CP-1")
        _seed_position(session_factory, "CP-1", "AAPL", 10, prior_close=200.0)
        _seed_vix(session_factory)
        _seed_latest_price(session_factory, "AAPL", 201.0)

        with (
            patch(
                "api.exposure.answer_csa_terms",
                return_value=_csa_result("CP-1", threshold=1_000_000.0),
            ),
            session_factory() as session,
        ):
            result = build_exposure_board(session)

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
        _seed_latest_price(session_factory, "AAPL", 210.0)

        with (
            patch(
                "api.exposure.answer_csa_terms",
                return_value=_csa_result("CP-1", threshold=500.0, mta=1.0),
            ),
            session_factory() as session,
        ):
            result = build_exposure_board(session)

        item = result.counterparties[0]
        assert item.exposure == pytest.approx(415.0)
        assert item.status == ExposureStatus.AT_RISK

    def test_breached_status_when_shortfall_clears_mta(self, session_factory) -> None:
        _seed_counterparty(session_factory, "CP-1")
        _seed_position(session_factory, "CP-1", "AAPL", 10, prior_close=200.0)
        _seed_vix(session_factory)
        _seed_latest_price(session_factory, "AAPL", 210.0)
        # No collateral seeded -- collateral_held is 0, so the full required
        # support becomes the call amount.

        with (
            patch(
                "api.exposure.answer_csa_terms",
                return_value=_csa_result("CP-1", threshold=100.0, mta=1.0),
            ),
            session_factory() as session,
        ):
            result = build_exposure_board(session)

        item = result.counterparties[0]
        assert item.status == ExposureStatus.BREACHED
        assert item.call_amount is not None and item.call_amount > 0

    def test_csa_terms_are_cached_across_counterparties_in_the_same_board(
        self, session_factory
    ) -> None:
        _seed_counterparty(session_factory, "CP-1")
        _seed_position(session_factory, "CP-1", "AAPL", 10, prior_close=200.0)
        _seed_vix(session_factory)
        _seed_latest_price(session_factory, "AAPL", 201.0)

        with patch(
            "api.exposure.answer_csa_terms", return_value=_csa_result("CP-1", threshold=1_000_000.0)
        ) as mock_answer:
            with session_factory() as session:
                build_exposure_board(session)
            with session_factory() as session:
                build_exposure_board(session)

        mock_answer.assert_called_once()

    def test_csa_terms_unavailable_is_also_cached_across_boards(self, session_factory) -> None:
        # MM-66 regression guard: lru_cache doesn't memoize raised
        # exceptions, so a counterparty with no CSA documents (e.g. a
        # leftover simulate-event test counterparty) used to re-run the real
        # RAG lookup on every single board request, forever -- this was the
        # dominant cost behind /exposure's slowness, past the SQL N+1 fix.
        _seed_counterparty(session_factory, "CP-1")
        _seed_position(session_factory, "CP-1", "AAPL", 10, prior_close=200.0)
        _seed_vix(session_factory)
        _seed_latest_price(session_factory, "AAPL", 201.0)

        with patch(
            "api.exposure.answer_csa_terms",
            side_effect=CSATermsUnavailableError("No CSA document chunks found for CP-1"),
        ) as mock_answer:
            with session_factory() as session:
                first = build_exposure_board(session)
            with session_factory() as session:
                second = build_exposure_board(session)

        mock_answer.assert_called_once()
        assert first.counterparties[0].status == ExposureStatus.UNAVAILABLE
        assert second.counterparties[0].status == ExposureStatus.UNAVAILABLE
        assert second.counterparties[0].detail == "No CSA document chunks found for CP-1"

    def test_vix_unavailable_is_unavailable_but_shows_positions(self, session_factory) -> None:
        _seed_counterparty(session_factory, "CP-1")
        _seed_position(session_factory, "CP-1", "AAPL", 10, prior_close=200.0)
        _seed_latest_price(session_factory, "AAPL", 201.0)
        # No VIXCLS reference rate seeded.

        with (
            patch(
                "api.exposure.answer_csa_terms",
                return_value=_csa_result("CP-1", threshold=1_000_000.0),
            ),
            session_factory() as session,
        ):
            result = build_exposure_board(session)

        item = result.counterparties[0]
        assert item.status == ExposureStatus.UNAVAILABLE
        assert "VIXCLS" in item.detail
        assert len(item.positions) == 1

    def test_vix_is_fetched_once_per_board_not_once_per_counterparty(self, session_factory) -> None:
        # MM-60 regression guard: latest_vix() used to be called inside the
        # per-counterparty loop even though VIX isn't counterparty-specific.
        _seed_counterparty(session_factory, "CP-1")
        _seed_position(session_factory, "CP-1", "AAPL", 10, prior_close=200.0)
        _seed_latest_price(session_factory, "AAPL", 201.0)
        _seed_counterparty(session_factory, "CP-2")
        _seed_position(session_factory, "CP-2", "TSLA", 5, prior_close=80.0)
        _seed_latest_price(session_factory, "TSLA", 82.0)

        with (
            patch(
                "api.exposure.answer_csa_terms",
                return_value=_csa_result("CP-X", threshold=1_000_000.0),
            ),
            patch("api.exposure.latest_vix", return_value=20.0) as mock_vix,
            session_factory() as session,
        ):
            result = build_exposure_board(session)

        mock_vix.assert_called_once()
        assert {cp.status for cp in result.counterparties} == {ExposureStatus.HEALTHY}

    def test_positions_and_collateral_are_batched_once_per_board_not_per_counterparty(
        self, session_factory
    ) -> None:
        # MM-66 regression guard: load_positions/collateral_held used to be
        # called inside the per-counterparty loop (N+1 SQL round trips).
        # wraps=... keeps the real DB-backed implementation so results are
        # still correct -- this only asserts *how many times* each query
        # function runs, not what it returns.
        import persistence.queries as queries_module

        _seed_counterparty(session_factory, "CP-1")
        _seed_position(session_factory, "CP-1", "AAPL", 10, prior_close=200.0)
        _seed_latest_price(session_factory, "AAPL", 201.0)
        _seed_counterparty(session_factory, "CP-2")
        _seed_position(session_factory, "CP-2", "TSLA", 5, prior_close=80.0)
        _seed_latest_price(session_factory, "TSLA", 82.0)
        _seed_vix(session_factory)

        with (
            patch(
                "api.exposure.answer_csa_terms",
                return_value=_csa_result("CP-X", threshold=1_000_000.0),
            ),
            patch(
                "api.exposure.load_positions_for_counterparties",
                wraps=queries_module.load_positions_for_counterparties,
            ) as mock_batched_positions,
            patch(
                "api.exposure.collateral_held_for_counterparties",
                wraps=queries_module.collateral_held_for_counterparties,
            ) as mock_batched_collateral,
            patch("api.exposure.load_positions") as mock_single_positions,
            patch("api.exposure.collateral_held") as mock_single_collateral,
            session_factory() as session,
        ):
            result = build_exposure_board(session)

        mock_batched_positions.assert_called_once()
        mock_batched_collateral.assert_called_once()
        mock_single_positions.assert_not_called()
        mock_single_collateral.assert_not_called()
        assert {cp.status for cp in result.counterparties} == {ExposureStatus.HEALTHY}

    def test_board_lists_every_counterparty(self, session_factory) -> None:
        _seed_counterparty(session_factory, "CP-1")
        _seed_counterparty(session_factory, "CP-2")

        with session_factory() as session:
            result = build_exposure_board(session)

        assert {cp.counterparty_id for cp in result.counterparties} == {"CP-1", "CP-2"}


class TestListCounterpartySummaries:
    def test_returns_id_and_name_for_every_counterparty(self, session_factory) -> None:
        _seed_counterparty(session_factory, "CP-1", name="Alpha")
        _seed_counterparty(session_factory, "CP-2", name="Beta")

        with session_factory() as session:
            result = list_counterparty_summaries(session)

        assert {(cp.counterparty_id, cp.counterparty_name) for cp in result.counterparties} == {
            ("CP-1", "Alpha"),
            ("CP-2", "Beta"),
        }

    def test_empty_when_no_counterparties(self, session_factory) -> None:
        with session_factory() as session:
            result = list_counterparty_summaries(session)

        assert result.counterparties == []

    def test_does_not_compute_exposure_or_touch_csa(self, session_factory) -> None:
        # MM-62 regression guard: the whole point is this stays a trivial DB
        # read, not the full board's per-counterparty computation.
        _seed_counterparty(session_factory, "CP-1")
        _seed_position(session_factory, "CP-1", "AAPL", 10, prior_close=200.0)
        # No LatestPriceORM, no VIX, no CSA mock -- would raise/error if
        # list_counterparty_summaries touched any of that.

        with session_factory() as session:
            result = list_counterparty_summaries(session)

        assert [cp.counterparty_id for cp in result.counterparties] == ["CP-1"]


class TestGetCounterpartyExposure:
    def test_returns_the_matching_counterparty_same_as_the_board(self, session_factory) -> None:
        _seed_counterparty(session_factory, "CP-1")
        _seed_position(session_factory, "CP-1", "AAPL", 10, prior_close=200.0)
        _seed_vix(session_factory)
        _seed_latest_price(session_factory, "AAPL", 201.0)

        with (
            patch(
                "api.exposure.answer_csa_terms",
                return_value=_csa_result("CP-1", threshold=1_000_000.0),
            ),
            session_factory() as session,
        ):
            result = get_counterparty_exposure(session, "CP-1")

        assert result is not None
        assert result.counterparty_id == "CP-1"
        assert result.status == ExposureStatus.HEALTHY

    def test_none_for_unknown_counterparty(self, session_factory) -> None:
        with session_factory() as session:
            assert get_counterparty_exposure(session, "CP-404") is None

    def test_does_not_compute_other_counterparties(self, session_factory) -> None:
        # MM-61 regression guard: the whole point is not fetching the rest
        # of the board just to answer for one counterparty.
        _seed_counterparty(session_factory, "CP-1")
        _seed_position(session_factory, "CP-1", "AAPL", 10, prior_close=200.0)
        _seed_latest_price(session_factory, "AAPL", 201.0)
        _seed_counterparty(session_factory, "CP-2")
        _seed_position(session_factory, "CP-2", "TSLA", 5, prior_close=80.0)
        _seed_latest_price(session_factory, "TSLA", 82.0)
        _seed_vix(session_factory)

        with (
            patch(
                "api.exposure.answer_csa_terms",
                return_value=_csa_result("CP-1", threshold=1_000_000.0),
            ) as mock_answer,
            session_factory() as session,
        ):
            get_counterparty_exposure(session, "CP-1")

        mock_answer.assert_called_once_with("CP-1")


class TestGetPriceHistory:
    def test_wraps_sql_rows_into_response(self) -> None:
        session = MagicMock()
        with patch(
            "api.exposure.price_history_rows",
            return_value=[
                PriceHistoryEntry(date=date(2026, 1, 1), price=100.0),
                PriceHistoryEntry(date=date(2026, 1, 2), price=105.0),
            ],
        ) as mock_rows:
            result = get_price_history(session, "AAPL", days=10)

        mock_rows.assert_called_once_with(session, "AAPL", days=10)
        assert result.ticker == "AAPL"
        assert [p.price for p in result.points] == [100.0, 105.0]

    def test_raises_market_data_unavailable_when_no_rows(self) -> None:
        session = MagicMock()
        with (
            patch("api.exposure.price_history_rows", return_value=[]),
            pytest.raises(MarketDataUnavailableError),
        ):
            get_price_history(session, "BADTICKER")
