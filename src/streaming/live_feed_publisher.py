from config.settings import Settings, get_settings
from streaming.market_feed import MarketFeed, get_market_feed
from streaming.producer import EventProducer


def publish_live_prices(
    tickers: list[str],
    producer: EventProducer | None = None,
    feed: MarketFeed | None = None,
    settings: Settings | None = None,
) -> int:
    """Publishes one tick per ticker onto market.prices, in the same PriceQuote
    schema/topic the simulator (MM-30) uses -- so the Event Agent's (MM-31)
    classification logic needs no live-specific branch. Respects
    MARKET_FEED_MODE via get_market_feed() unless a feed is injected."""
    settings = settings or get_settings()
    producer = producer or EventProducer(settings)
    feed = feed or get_market_feed(settings)

    quotes = feed.get_prices(tickers)
    for ticker, quote in quotes.items():
        producer.publish(settings.kafka_topic_prices, quote, key=ticker)
    producer.flush()
    return len(quotes)
