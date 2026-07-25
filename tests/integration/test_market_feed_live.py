"""Real network calls against yfinance + CoinGecko. Excluded from the default
/CI test run (see the `live` marker in pyproject.toml) since they depend on
free third-party APIs that can rate-limit or be transiently unavailable.

Run explicitly with: pytest -m live tests/integration/test_market_feed_live.py
"""

import pytest

from streaming.market_feed import CoinGeckoFeed, CompositeMarketFeed, YFinanceFeed

pytestmark = pytest.mark.live


def test_yfinance_returns_real_prices_for_canary_tickers() -> None:
    result = YFinanceFeed().get_prices(["AAPL", "SPY"])

    assert result["AAPL"].price > 0
    assert result["SPY"].price > 0


def test_coingecko_returns_real_price_for_btc() -> None:
    result = CoinGeckoFeed().get_prices(["BTC-USD"])

    assert result["BTC-USD"].price > 0


def test_composite_feed_prices_mixed_universe_subset() -> None:
    result = CompositeMarketFeed().get_prices(["AAPL", "SPY", "BTC-USD"])

    assert len(result) == 3
    assert all(quote.price > 0 for quote in result.values())
