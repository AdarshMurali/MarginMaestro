from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from streaming.live_feed_publisher import publish_live_prices
from streaming.market_feed import PriceQuote


def _quote(ticker: str, price: float) -> PriceQuote:
    return PriceQuote(ticker=ticker, price=price, as_of=datetime.now(UTC), source="yfinance")


def test_publishes_one_tick_per_ticker_to_prices_topic() -> None:
    feed = MagicMock()
    feed.get_prices.return_value = {"AAPL": _quote("AAPL", 200.0), "TSLA": _quote("TSLA", 300.0)}
    producer = MagicMock()

    count = publish_live_prices(["AAPL", "TSLA"], producer=producer, feed=feed)

    assert count == 2
    feed.get_prices.assert_called_once_with(["AAPL", "TSLA"])
    published_topics = {call.args[0] for call in producer.publish.call_args_list}
    assert published_topics == {"market.prices"}
    published_keys = {call.kwargs["key"] for call in producer.publish.call_args_list}
    assert published_keys == {"AAPL", "TSLA"}
    producer.flush.assert_called_once()


def test_returns_zero_and_still_flushes_when_feed_has_nothing() -> None:
    feed = MagicMock()
    feed.get_prices.return_value = {}
    producer = MagicMock()

    count = publish_live_prices(["AAPL"], producer=producer, feed=feed)

    assert count == 0
    producer.publish.assert_not_called()
    producer.flush.assert_called_once()


def test_uses_get_market_feed_when_no_feed_injected() -> None:
    producer = MagicMock()
    fallback_feed = MagicMock()
    fallback_feed.get_prices.return_value = {"AAPL": _quote("AAPL", 200.0)}

    with patch(
        "streaming.live_feed_publisher.get_market_feed", return_value=fallback_feed
    ) as mock_get_feed:
        count = publish_live_prices(["AAPL"], producer=producer)

    mock_get_feed.assert_called_once()
    assert count == 1
