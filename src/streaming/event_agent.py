from datetime import UTC, datetime

import structlog
from confluent_kafka import Message
from sqlalchemy import select
from sqlalchemy.orm import Session

from config.settings import Settings, get_settings
from persistence.db.engine import get_session_factory
from persistence.db.models import (
    LatestPriceORM,
    PortfolioORM,
    PositionORM,
    PriceHistoryORM,
    ProcessedEventORM,
)
from streaming.consumer import EventConsumer, decode
from streaming.market_feed import PriceQuote
from streaming.producer import EventProducer
from streaming.schemas import ImpactSet, MarketEvent, MarketEventType

logger = structlog.get_logger()

# Stateless per-tick thresholds (ADR-0003: no windowed/stateful computation --
# a real windowed job is what would eventually justify adding Flink).
PRICE_SHOCK_THRESHOLD = 0.07
VOL_SPIKE_THRESHOLD = 0.15


def classify_price_move(quote: PriceQuote, prior_close: float) -> MarketEventType | None:
    if prior_close <= 0:
        return None
    pct_change = abs(quote.price - prior_close) / prior_close
    if pct_change >= VOL_SPIKE_THRESHOLD:
        return MarketEventType.VOL_SPIKE
    if pct_change >= PRICE_SHOCK_THRESHOLD:
        return MarketEventType.PRICE_SHOCK
    return None


def price_event_id(quote: PriceQuote) -> str:
    """Deterministic from message content, so a redelivered (not re-generated)
    tick maps to the same id -- required for the idempotency check to work."""
    return f"{quote.ticker}:{quote.as_of.isoformat()}:{quote.source}"


def is_already_processed(session: Session, event_id: str) -> bool:
    return session.get(ProcessedEventORM, event_id) is not None


def mark_processed(session: Session, event_id: str) -> None:
    session.merge(ProcessedEventORM(event_id=event_id, processed_at=datetime.now(UTC)))
    session.commit()


def upsert_latest_price(session: Session, quote: PriceQuote) -> None:
    """Unconditional on every tick (MM-59) -- called before dedup/threshold
    checks in handle_price_message. Most ticks never cross the shock/spike
    threshold, so if this ran after those checks the latest-price table
    would almost never update; this is the sole read-time source for
    /exposure's current price and the price chart, so it must reflect every
    tick, not just the ones that turn into an ImpactSet."""
    session.merge(
        LatestPriceORM(
            ticker=quote.ticker,
            price=quote.price,
            currency=quote.currency,
            source=quote.source,
            as_of=quote.as_of,
            updated_at=datetime.now(UTC),
        )
    )
    session.commit()


def latest_close_before(session: Session, ticker: str, before: datetime) -> float | None:
    row = session.execute(
        select(PriceHistoryORM.price)
        .where(PriceHistoryORM.ticker == ticker, PriceHistoryORM.price_date < before.date())
        .order_by(PriceHistoryORM.price_date.desc())
        .limit(1)
    ).scalar_one_or_none()
    return row


def affected_counterparties(session: Session, ticker: str) -> list[str]:
    rows = session.execute(
        select(PortfolioORM.counterparty_id)
        .join(PositionORM, PositionORM.portfolio_id == PortfolioORM.id)
        .where(PositionORM.ticker == ticker)
        .distinct()
    ).scalars()
    return sorted(rows)


def handle_price_message(
    session: Session, quote: PriceQuote, producer: EventProducer, settings: Settings
) -> ImpactSet | None:
    upsert_latest_price(session, quote)

    event_id = price_event_id(quote)
    if is_already_processed(session, event_id):
        return None

    prior_close = latest_close_before(session, quote.ticker, quote.as_of)
    if prior_close is None:
        mark_processed(session, event_id)
        return None

    event_type = classify_price_move(quote, prior_close)
    if event_type is None:
        mark_processed(session, event_id)
        return None

    pct_change = abs(quote.price - prior_close) / prior_close
    impact = ImpactSet(
        event_id=event_id,
        event_type=event_type,
        counterparty_ids=affected_counterparties(session, quote.ticker),
        reason=f"{quote.ticker} moved {pct_change:.1%} vs prior close ({prior_close} -> {quote.price})",
        occurred_at=quote.as_of,
    )
    producer.publish(settings.kafka_topic_impact, impact, key=event_id)
    producer.flush()
    mark_processed(session, event_id)
    return impact


def handle_market_event_message(
    session: Session, event: MarketEvent, producer: EventProducer, settings: Settings
) -> ImpactSet | None:
    if is_already_processed(session, event.event_id):
        return None

    impact = ImpactSet(
        event_id=event.event_id,
        event_type=event.event_type,
        counterparty_ids=[event.counterparty_id] if event.counterparty_id else [],
        reason=event.description,
        occurred_at=event.occurred_at,
    )
    producer.publish(settings.kafka_topic_impact, impact, key=event.event_id)
    producer.flush()
    mark_processed(session, event.event_id)
    return impact


def handle_message(
    session: Session,
    msg: Message,
    producer: EventProducer,
    settings: Settings,
) -> ImpactSet | None:
    if msg.topic() == settings.kafka_topic_prices:
        return handle_price_message(session, decode(msg, PriceQuote), producer, settings)
    return handle_market_event_message(session, decode(msg, MarketEvent), producer, settings)


def run(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    session_factory = get_session_factory(settings)
    producer = EventProducer(settings)

    with EventConsumer(
        topics=[settings.kafka_topic_prices, settings.kafka_topic_events],
        group_id="event-agent",
        settings=settings,
    ) as consumer:
        while True:
            msg = consumer.poll(1.0)
            if msg is None:
                continue
            with session_factory() as session:
                handle_message(session, msg, producer, settings)
            consumer.commit(msg)


if __name__ == "__main__":
    run()
