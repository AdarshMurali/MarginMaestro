from datetime import UTC, date, datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from persistence.batch_loader import (
    backfill_price_history,
    load_prices,
    load_reference_rates,
    load_synthetic_reference_data,
    main,
    run_batch_load,
)
from persistence.db.models import (
    AuditLogORM,
    Base,
    CollateralItemORM,
    CounterpartyORM,
    PortfolioORM,
    PositionORM,
    PriceHistoryORM,
    RatingORM,
)
from persistence.fred_feed import REFERENCE_SERIES, RateObservation
from streaming.market_feed import MarketDataUnavailableError, PriceHistoryPoint, PriceQuote


class TestLoadSyntheticReferenceData:
    def test_merges_every_generated_record_type(self) -> None:
        session = MagicMock()

        counts = load_synthetic_reference_data(session, seed=42, as_of=date(2026, 7, 26))

        assert counts["counterparties"] == 8
        assert session.merge.call_count == sum(counts.values())
        merged_types = {type(call.args[0]) for call in session.merge.call_args_list}
        assert merged_types == {
            CounterpartyORM,
            PortfolioORM,
            PositionORM,
            RatingORM,
            CollateralItemORM,
        }


class TestLoadPrices:
    def test_merges_a_price_history_row_per_quote(self) -> None:
        session = MagicMock()
        feed = MagicMock()
        now = datetime.now(UTC)
        feed.get_prices.return_value = {
            "AAPL": PriceQuote(ticker="AAPL", price=333.0, as_of=now, source="yfinance"),
            "BTC-USD": PriceQuote(ticker="BTC-USD", price=64000.0, as_of=now, source="coingecko"),
        }

        count = load_prices(session, feed, ["AAPL", "BTC-USD"], as_of=date(2026, 7, 26))

        assert count == 2
        assert session.merge.call_count == 2
        feed.get_prices.assert_called_once_with(["AAPL", "BTC-USD"])


class TestLoadReferenceRates:
    def test_merges_a_rate_row_per_series(self) -> None:
        session = MagicMock()
        feed = MagicMock()
        feed.get_latest.side_effect = lambda series_id: RateObservation(
            series_id=series_id, date=date(2026, 7, 23), value=4.0
        )

        count = load_reference_rates(session, feed, as_of=date(2026, 7, 26))

        assert count == len(REFERENCE_SERIES)
        assert session.merge.call_count == len(REFERENCE_SERIES)
        assert feed.get_latest.call_count == len(REFERENCE_SERIES)


class TestBackfillPriceHistory:
    @pytest.fixture
    def session_factory(self):
        engine = create_engine(
            "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(engine)
        return sessionmaker(bind=engine)

    def test_skips_ticker_with_enough_existing_rows(self, session_factory) -> None:
        with session_factory() as session:
            for i in range(5):
                session.add(
                    PriceHistoryORM(
                        ticker="AAPL",
                        price_date=date(2026, 7, 1 + i),
                        price=200.0,
                        currency="USD",
                        source="yfinance",
                    )
                )
            session.commit()

        with (
            session_factory() as session,
            patch("persistence.batch_loader.fetch_ticker_price_history") as mock_fetch,
        ):
            inserted = backfill_price_history(session, ["AAPL"], min_existing_rows=5)

        assert inserted == 0
        mock_fetch.assert_not_called()

    def test_backfills_ticker_below_the_row_threshold(self, session_factory) -> None:
        with (
            session_factory() as session,
            patch(
                "persistence.batch_loader.fetch_ticker_price_history",
                return_value=[
                    PriceHistoryPoint(date=date(2026, 7, 1), price=200.0),
                    PriceHistoryPoint(date=date(2026, 7, 2), price=201.0),
                ],
            ),
        ):
            inserted = backfill_price_history(session, ["AAPL"], min_existing_rows=5)

        assert inserted == 2

    def test_tolerates_one_tickers_market_data_unavailable(self, session_factory) -> None:
        def fake_fetch(ticker: str, days: int) -> list[PriceHistoryPoint]:
            if ticker == "BADTICKER":
                raise MarketDataUnavailableError(ticker)
            return [PriceHistoryPoint(date=date(2026, 7, 1), price=100.0)]

        with (
            session_factory() as session,
            patch("persistence.batch_loader.fetch_ticker_price_history", side_effect=fake_fetch),
        ):
            inserted = backfill_price_history(session, ["BADTICKER", "AAPL"], min_existing_rows=5)

        assert inserted == 1


class TestRunBatchLoad:
    def test_orchestrates_loads_and_commits_with_audit_log(self) -> None:
        session = MagicMock()
        session_context = MagicMock()
        session_context.__enter__.return_value = session
        session_context.__exit__.return_value = None
        session_factory = MagicMock(return_value=session_context)

        market_feed = MagicMock()
        market_feed.get_prices.return_value = {
            "AAPL": PriceQuote(
                ticker="AAPL", price=333.0, as_of=datetime.now(UTC), source="yfinance"
            )
        }

        fred_feed_instance = MagicMock()
        fred_feed_instance.get_latest.return_value = RateObservation(
            series_id="SOFR", date=date(2026, 7, 23), value=4.0
        )

        with (
            patch("persistence.batch_loader.get_settings") as mock_get_settings,
            patch("persistence.batch_loader.ensure_database_exists") as mock_ensure_db,
            patch("persistence.batch_loader.get_session_factory", return_value=session_factory),
            patch("persistence.batch_loader.get_market_feed", return_value=market_feed),
            patch("persistence.batch_loader.FredFeed", return_value=fred_feed_instance),
            # session here is a MagicMock, not a real DB session -- backfill's
            # own SQL-query behavior is covered by TestBackfillPriceHistory
            # against a real (in-memory) session; this test only needs to
            # confirm run_batch_load wires it in and folds its count into
            # the summary.
            patch(
                "persistence.batch_loader.backfill_price_history", return_value=0
            ) as mock_backfill,
            # Same rationale as backfill_price_history above -- its own
            # behavior against a real session is covered by
            # test_collateral_calibration.py; this test only needs to
            # confirm run_batch_load wires it in after prices are loaded and
            # folds its result count into the summary.
            patch(
                "persistence.batch_loader.calibrate_collateral_to_exposure",
                return_value={"CP-1": 500_000.0},
            ) as mock_calibrate,
        ):
            summary = run_batch_load(seed=42, as_of=date(2026, 7, 26))

        mock_ensure_db.assert_called_once_with(mock_get_settings.return_value)
        assert summary["counterparties"] == 8
        assert summary["prices"] == 1
        assert summary["reference_rates"] == len(REFERENCE_SERIES)
        assert summary["price_history_backfill"] == 0
        assert summary["collateral_calibrated"] == 1
        mock_backfill.assert_called_once()
        mock_calibrate.assert_called_once_with(session, 42, date(2026, 7, 26))
        session.commit.assert_called_once()

        audit_rows = [
            call.args[0]
            for call in session.add.call_args_list
            if isinstance(call.args[0], AuditLogORM)
        ]
        assert len(audit_rows) == 1
        assert audit_rows[0].event_type == "batch_load"
        assert audit_rows[0].payload == summary


class TestMain:
    def test_parses_seed_and_prints_summary(self, capsys) -> None:
        with (
            patch(
                "persistence.batch_loader.run_batch_load", return_value={"prices": 1}
            ) as mock_run,
            patch("sys.argv", ["batch_loader", "--seed", "7"]),
        ):
            main()

        mock_run.assert_called_once_with(seed=7)
        assert "prices" in capsys.readouterr().out
