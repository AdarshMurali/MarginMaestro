import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Protocol

import httpx
import yfinance as yf
from pydantic import BaseModel

from config.settings import Settings, get_settings
from persistence.generators.securities import COINGECKO_ID_MAP, asset_class_for
from persistence.models import AssetClass

COINGECKO_API_BASE = "https://api.coingecko.com/api/v3"
COINGECKO_SIMPLE_PRICE_URL = f"{COINGECKO_API_BASE}/simple/price"

# CoinGecko's free/anonymous tier enforces a stricter, undocumented rate
# limit than its published "Demo" tier -- a transient 429 shouldn't fail a
# whole price/history request outright, so every CoinGecko call retries
# through this helper before giving up.
COINGECKO_MAX_RETRIES = 3
COINGECKO_BACKOFF_SECONDS = 1.0


def _get_with_retry(
    client: httpx.Client,
    url: str,
    params: dict[str, str],
    max_retries: int = COINGECKO_MAX_RETRIES,
    backoff_seconds: float = COINGECKO_BACKOFF_SECONDS,
    sleep: Callable[[float], None] | None = None,
) -> httpx.Response:
    """GETs url, retrying on HTTP 429 with exponential backoff -- honors a
    Retry-After response header when CoinGecko sends one, otherwise
    backoff_seconds * 2**attempt. `sleep` defaults to time.sleep, looked up
    at call time (not bound as a default) so tests can patch
    streaming.market_feed.time.sleep even through CoinGeckoFeed/
    _coingecko_history, which don't expose their own sleep param."""
    sleep = sleep or time.sleep
    response = client.get(url, params=params)
    attempt = 0
    while response.status_code == 429 and attempt < max_retries:
        retry_after = response.headers.get("Retry-After")
        delay = float(retry_after) if retry_after is not None else backoff_seconds * (2**attempt)
        sleep(delay)
        response = client.get(url, params=params)
        attempt += 1
    return response


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
        response = _get_with_retry(
            self._client,
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


class PriceHistoryPoint(BaseModel):
    date: date
    price: float


def _yfinance_history(ticker: str, days: int) -> list[PriceHistoryPoint]:
    start = (datetime.now(UTC) - timedelta(days=days)).date()
    history = yf.Ticker(ticker).history(start=start)
    if history.empty:
        raise MarketDataUnavailableError(f"No price history available for {ticker}")
    return [
        PriceHistoryPoint(date=index.date(), price=float(row["Close"]))
        for index, row in history.iterrows()
    ]


def _coingecko_history(
    ticker: str, days: int, client: httpx.Client | None = None
) -> list[PriceHistoryPoint]:
    coingecko_id = COINGECKO_ID_MAP.get(ticker)
    if coingecko_id is None:
        raise MarketDataUnavailableError(f"No CoinGecko id mapping for: {ticker}")

    client = client or httpx.Client(timeout=10.0)
    response = _get_with_retry(
        client,
        f"{COINGECKO_API_BASE}/coins/{coingecko_id}/market_chart",
        params={"vs_currency": "usd", "days": str(days)},
    )
    if response.status_code != 200:
        raise MarketDataUnavailableError(
            f"CoinGecko history request failed with status {response.status_code}"
        )

    prices = response.json().get("prices", [])
    if not prices:
        raise MarketDataUnavailableError(f"No price history available for {ticker}")

    # CoinGecko returns hourly-or-finer samples for short windows -- collapse
    # to one point per calendar day (last sample of the day wins) so this
    # lines up with yfinance's daily granularity for the same chart.
    points_by_date: dict[date, float] = {}
    for timestamp_ms, price in prices:
        point_date = datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC).date()
        points_by_date[point_date] = price
    return [PriceHistoryPoint(date=d, price=p) for d, p in sorted(points_by_date.items())]


def get_price_history(
    ticker: str, days: int = 30, client: httpx.Client | None = None
) -> list[PriceHistoryPoint]:
    """Real historical daily closes -- yfinance for equities/ETFs, CoinGecko
    for crypto (same asset-class routing as CompositeMarketFeed). Distinct
    from the `price_history` DB table (a thin single-batch-run snapshot, not
    a real time series yet) -- fetched live so the chart shows genuine
    history rather than near-empty seed data."""
    if asset_class_for(ticker) == AssetClass.CRYPTO:
        return _coingecko_history(ticker, days, client=client)
    return _yfinance_history(ticker, days)


def get_market_feed(settings: Settings | None = None) -> MarketFeed:
    settings = settings or get_settings()
    if settings.market_feed_mode == "live":
        return CompositeMarketFeed()
    if settings.market_feed_mode == "simulated":
        from streaming.simulator import SimulatedMarketFeed

        return SimulatedMarketFeed()
    raise ValueError(f"Unknown MARKET_FEED_MODE: {settings.market_feed_mode!r}")
