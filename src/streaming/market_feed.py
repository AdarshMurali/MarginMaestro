from datetime import UTC, datetime
from typing import Protocol

import httpx
import yfinance as yf
from pydantic import BaseModel

from config.settings import Settings, get_settings
from persistence.generators.securities import COINGECKO_ID_MAP, asset_class_for
from persistence.models import AssetClass

COINGECKO_SIMPLE_PRICE_URL = "https://api.coingecko.com/api/v3/simple/price"


class PriceQuote(BaseModel):
    ticker: str
    price: float
    currency: str = "USD"
    as_of: datetime
    source: str


class MarketDataUnavailableError(Exception):
    """Raised when one or more requested tickers could not be priced."""


class MarketFeed(Protocol):
    def get_prices(self, tickers: list[str]) -> dict[str, PriceQuote]: ...


class YFinanceFeed:
    """Prices equities/ETFs via yfinance (free, no API key)."""

    def get_prices(self, tickers: list[str]) -> dict[str, PriceQuote]:
        if not tickers:
            return {}

        now = datetime.now(UTC)
        results: dict[str, PriceQuote] = {}
        failed: list[str] = []

        yf_tickers = yf.Tickers(" ".join(tickers))
        for ticker in tickers:
            try:
                last_price = yf_tickers.tickers[ticker].fast_info["last_price"]
            except (KeyError, IndexError, AttributeError):
                last_price = None
            if last_price is None:
                failed.append(ticker)
                continue
            results[ticker] = PriceQuote(
                ticker=ticker, price=float(last_price), as_of=now, source="yfinance"
            )

        if failed:
            raise MarketDataUnavailableError(f"yfinance could not price: {', '.join(failed)}")
        return results


class CoinGeckoFeed:
    """Prices crypto via CoinGecko's free public REST API (no API key)."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=10.0)

    def get_prices(self, tickers: list[str]) -> dict[str, PriceQuote]:
        if not tickers:
            return {}

        missing_map = [t for t in tickers if t not in COINGECKO_ID_MAP]
        if missing_map:
            raise MarketDataUnavailableError(
                f"No CoinGecko id mapping for: {', '.join(missing_map)}"
            )

        ids_by_ticker = {t: COINGECKO_ID_MAP[t] for t in tickers}
        response = self._client.get(
            COINGECKO_SIMPLE_PRICE_URL,
            params={"ids": ",".join(ids_by_ticker.values()), "vs_currencies": "usd"},
        )
        if response.status_code != 200:
            raise MarketDataUnavailableError(
                f"CoinGecko request failed with status {response.status_code}"
            )
        payload = response.json()

        now = datetime.now(UTC)
        results: dict[str, PriceQuote] = {}
        failed: list[str] = []
        for ticker, coingecko_id in ids_by_ticker.items():
            price = payload.get(coingecko_id, {}).get("usd")
            if price is None:
                failed.append(ticker)
                continue
            results[ticker] = PriceQuote(
                ticker=ticker, price=float(price), as_of=now, source="coingecko"
            )

        if failed:
            raise MarketDataUnavailableError(f"CoinGecko could not price: {', '.join(failed)}")
        return results


class CompositeMarketFeed:
    """Routes each ticker to the yfinance or CoinGecko feed by asset class."""

    def __init__(
        self, equity_feed: MarketFeed | None = None, crypto_feed: MarketFeed | None = None
    ) -> None:
        self._equity_feed = equity_feed or YFinanceFeed()
        self._crypto_feed = crypto_feed or CoinGeckoFeed()

    def get_prices(self, tickers: list[str]) -> dict[str, PriceQuote]:
        crypto = [t for t in tickers if asset_class_for(t) == AssetClass.CRYPTO]
        equity = [t for t in tickers if asset_class_for(t) != AssetClass.CRYPTO]

        results: dict[str, PriceQuote] = {}
        if equity:
            results.update(self._equity_feed.get_prices(equity))
        if crypto:
            results.update(self._crypto_feed.get_prices(crypto))
        return results


def get_market_feed(settings: Settings | None = None) -> MarketFeed:
    settings = settings or get_settings()
    if settings.market_feed_mode == "live":
        return CompositeMarketFeed()
    if settings.market_feed_mode == "simulated":
        from streaming.simulator import SimulatedMarketFeed

        return SimulatedMarketFeed()
    raise ValueError(f"Unknown MARKET_FEED_MODE: {settings.market_feed_mode!r}")
