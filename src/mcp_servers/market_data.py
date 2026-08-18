from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from streaming.market_feed import get_market_feed, get_price_history

mcp = FastMCP("market-data")


@mcp.tool()
def get_current_prices(
    tickers: Annotated[
        list[str],
        Field(description="Tickers from the curated MARKET_UNIVERSE, e.g. ['AAPL', 'BTC-USD']."),
    ],
) -> list[dict]:
    """Get current prices for one or more tickers -- routed to yfinance
    (equities/ETFs) or CoinGecko (crypto) by asset class, per
    MARKET_FEED_MODE. Raises MarketDataUnavailableError if any requested
    ticker can't be priced.
    """
    feed = get_market_feed()
    quotes = feed.get_prices(tickers)
    return [quote.model_dump() for quote in quotes.values()]


@mcp.tool()
def get_historical_prices(
    ticker: Annotated[str, Field(description="A single ticker from the curated MARKET_UNIVERSE.")],
    days: Annotated[
        int, Field(description="Number of trailing days of daily closes to return.", ge=1)
    ] = 30,
) -> list[dict]:
    """Get daily historical closes for one ticker over the trailing `days`
    -- always a real live lookup (yfinance/CoinGecko), independent of
    MARKET_FEED_MODE. Raises MarketDataUnavailableError if no history is
    available for the ticker.
    """
    return [point.model_dump() for point in get_price_history(ticker, days=days)]


if __name__ == "__main__":
    mcp.run()
