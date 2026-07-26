from datetime import UTC, date, datetime
from unittest.mock import MagicMock

from persistence.batch_loader import (
    load_prices,
    load_reference_rates,
    load_synthetic_reference_data,
)
from persistence.db.models import (
    CollateralItemORM,
    CounterpartyORM,
    PortfolioORM,
    PositionORM,
    RatingORM,
)
from persistence.fred_feed import REFERENCE_SERIES, RateObservation
from streaming.market_feed import PriceQuote


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
