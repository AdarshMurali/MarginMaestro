import time
from collections.abc import Callable
from datetime import UTC, datetime

import structlog
from confluent_kafka import Message
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from config.settings import Settings, get_settings
from persistence.db.engine import get_session_factory
from persistence.db.models import (
    LatestPriceORM,
    PortfolioORM,
    PositionORM,
    PriceHistoryORM,
    ProcessedEventORM,
    RatingORM,
)
from streaming.consumer import EventConsumer, decode
from streaming.market_feed import PriceQuote
from streaming.producer import EventProducer
from streaming.schemas import DeadLetterEvent, ImpactSet, MarketEvent, MarketEventType

logger = structlog.get_logger()

# Stateless per-tick thresholds (ADR-0003: no windowed/stateful computation --
# a real windowed job is what would eventually justify adding Flink).
PRICE_SHOCK_THRESHOLD = 0.07
VOL_SPIKE_THRESHOLD = 0.15

# MM-93: bounded retry budget for one message before it's routed to the
# dead-letter topic. Uniform across every exception type (decode failures,
# DB blips, producer delivery errors) rather than trying to classify which
# are "worth" retrying -- a deterministic failure just costs a few seconds
# of backoff before landing in the DLQ where it's visible, versus the
# previous behavior (an uncaught exception crashed the whole consumer
# process without committing the offset, so the exact same message would be
# redelivered and crash it again on every restart -- a permanent crash-loop
# that wedges the partition for every message behind it).
EVENT_AGENT_MAX_ATTEMPTS = 3
EVENT_AGENT_RETRY_BACKOFF_SECONDS = 1.0


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


def upsert_rating_downgrade(session: Session, event: MarketEvent) -> None:
    """Persists a DOWNGRADE event's new rating so evaluate_breach_node can
    read a real "current rating" -- without this, rating_triggers would
    never actually fire from a live simulated downgrade. One row per
    counterparty (id keyed by counterparty, not event_id) so a replayed
    downgrade re-merges the same row instead of accumulating history --
    matches upsert_latest_price's unconditional-overwrite pattern above."""
    if event.counterparty_id is None or event.new_rating_grade is None:
        return
    session.merge(
        RatingORM(
            id=f"RTG-DG-{event.counterparty_id}",
            counterparty_id=event.counterparty_id,
            grade=event.new_rating_grade.value,
            rating_date=event.occurred_at.date(),
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
    if event.event_type is MarketEventType.DOWNGRADE:
        upsert_rating_downgrade(session, event)

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


def _dead_letter_event(msg: Message, error: Exception, attempts: int) -> DeadLetterEvent:
    # confluent_kafka's stubs type these as Optional (a raw error Message can
    # lack them), but EventConsumer.poll() already filters error messages
    # out before anything reaches here -- a real, successfully polled
    # message always has all three set.
    topic, partition, offset = msg.topic(), msg.partition(), msg.offset()
    assert topic is not None and partition is not None and offset is not None
    key = msg.key()
    value = msg.value()
    return DeadLetterEvent(
        topic=topic,
        partition=partition,
        offset=offset,
        key=key.decode("utf-8", errors="replace") if key is not None else None,
        value=value.decode("utf-8", errors="replace") if value is not None else "",
        error_type=type(error).__name__,
        error_message=str(error),
        attempts=attempts,
        failed_at=datetime.now(UTC),
    )


def _publish_dead_letter(
    msg: Message, error: Exception, attempts: int, producer: EventProducer, settings: Settings
) -> None:
    """Deliberately doesn't catch its own failure -- if Redpanda itself is
    unreachable, publish()/flush() raising and propagating out of
    _handle_with_retry (and in turn run()'s loop) is the right outcome: the
    original message's offset never gets committed, so it's naturally
    redelivered and retried after a restart, exactly like any other
    unhandled failure today. The dead-letter path only replaces
    "crash forever on this one message" with "crash if the broker itself is
    down" -- a materially bigger, more visible problem than one bad message."""
    dead_letter = _dead_letter_event(msg, error, attempts)
    dlq_key = f"{dead_letter.topic}:{dead_letter.partition}:{dead_letter.offset}"
    producer.publish(settings.kafka_topic_dead_letter, dead_letter, key=dlq_key)
    producer.flush()
    logger.error(
        "event_agent_dead_lettered",
        topic=dead_letter.topic,
        partition=dead_letter.partition,
        offset=dead_letter.offset,
        attempts=attempts,
        error=str(error),
    )


def _handle_with_retry(
    msg: Message,
    producer: EventProducer,
    settings: Settings,
    session_factory: sessionmaker[Session],
    max_attempts: int = EVENT_AGENT_MAX_ATTEMPTS,
    backoff_seconds: float = EVENT_AGENT_RETRY_BACKOFF_SECONDS,
    sleep: Callable[[float], None] | None = None,
) -> ImpactSet | None:
    """A fresh session per attempt -- a session that raised mid-transaction
    can't just be reused for the next attempt. Every exception is retried
    the same way (see EVENT_AGENT_MAX_ATTEMPTS's docstring); once the budget
    is exhausted the message is dead-lettered rather than re-raised, so the
    caller can always commit the offset and move on to the next message."""
    sleep = sleep or time.sleep
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            with session_factory() as session:
                return handle_message(session, msg, producer, settings)
        except Exception as exc:  # noqa: BLE001 -- catch-all is deliberate, see docstring above
            last_error = exc
            logger.warning(
                "event_agent_handle_failed",
                attempt=attempt,
                max_attempts=max_attempts,
                error=str(exc),
            )
            if attempt < max_attempts:
                sleep(backoff_seconds * (2 ** (attempt - 1)))

    assert last_error is not None  # loop always sets it before falling through
    _publish_dead_letter(msg, last_error, max_attempts, producer, settings)
    return None


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
            _handle_with_retry(msg, producer, settings, session_factory)
            consumer.commit(msg)


if __name__ == "__main__":
    run()
