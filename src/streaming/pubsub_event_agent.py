"""Event Agent over Pub/Sub pull (MM-120) -- the Pub/Sub counterpart to
`event_agent.run()`'s Kafka loop, with the same handling, retry and
dead-letter code (`_handle_with_retry`):

    EVENT_BUS=pubsub GCP_PROJECT_ID=marginmaestro-demo python -m streaming.pubsub_event_agent

It pulls from the `event-agent.<topic>` subscriptions on `market.prices` and
`market.events`, so each price tick upserts `latest_prices` and a big move
publishes an impact set to `market.impact`. On the emulator
(`PUBSUB_EMULATOR_HOST`) it creates the subscriptions itself; on GCP they are
Terraform-managed. In G5 the same subscriptions push to the Event Agent on
Cloud Run (MM-121) and this loop is only for local runs.

A message is acked only after it has been handled or dead-lettered. If
dead-lettering itself fails, the error propagates and the message is
redelivered -- safe, because handling is idempotent (`processed_events`).
"""

import itertools
import os
import time
from typing import Any

import structlog
from sqlalchemy.orm import Session, sessionmaker

from adapters.factory import get_event_bus
from adapters.pubsub_admin import ensure_subscriptions, event_agent_subscription, event_agent_topics
from config.settings import Settings, get_settings
from persistence.db.engine import get_session_factory
from ports.event_bus import EventBus
from streaming.event_agent import _handle_with_retry
from streaming.inbound import PubSubInbound

logger = structlog.get_logger()

PULL_MAX_MESSAGES = 10
PULL_TIMEOUT_SECONDS = 5.0
IDLE_SLEEP_SECONDS = 1.0


def drain_once(
    subscriber: Any,
    subscriptions: dict[str, str],
    producer: EventBus,
    settings: Settings,
    session_factory: sessionmaker[Session],
    max_messages: int = PULL_MAX_MESSAGES,
) -> int:
    """One pull per subscription (`subscriptions` maps topic -> subscription
    path); returns how many messages were handled."""
    from google.api_core.exceptions import DeadlineExceeded

    handled = 0
    for topic, path in subscriptions.items():
        try:
            response = subscriber.pull(
                request={"subscription": path, "max_messages": max_messages},
                timeout=PULL_TIMEOUT_SECONDS,
            )
        except DeadlineExceeded:
            continue  # nothing waiting on this subscription
        for received in response.received_messages:
            _handle_with_retry(
                PubSubInbound(topic, received.message), producer, settings, session_factory
            )
            subscriber.acknowledge(request={"subscription": path, "ack_ids": [received.ack_id]})
            handled += 1
    return handled


def run(
    settings: Settings | None = None,
    subscriber: Any | None = None,
    max_iterations: int | None = None,
) -> None:
    """`max_iterations` bounds the loop for tests; leave it None to run until stopped."""
    settings = settings or get_settings()
    if settings.event_bus != "pubsub" or not settings.gcp_project_id:
        raise ValueError("pubsub_event_agent needs EVENT_BUS=pubsub and GCP_PROJECT_ID")
    project = settings.gcp_project_id

    if subscriber is None:
        from google.cloud.pubsub_v1 import SubscriberClient

        subscriber = SubscriberClient()
    topics = event_agent_topics(settings)
    if os.environ.get("PUBSUB_EMULATOR_HOST"):
        ensure_subscriptions(project, topics, subscriber=subscriber)
    subscriptions = {
        topic: subscriber.subscription_path(project, event_agent_subscription(topic))
        for topic in topics
    }
    producer = get_event_bus(settings)
    session_factory = get_session_factory(settings)
    logger.info("pubsub_event_agent_started", subscriptions=list(subscriptions.values()))

    iterations = range(max_iterations) if max_iterations is not None else itertools.count()
    for _ in iterations:
        if drain_once(subscriber, subscriptions, producer, settings, session_factory) == 0:
            time.sleep(IDLE_SLEEP_SECONDS)


if __name__ == "__main__":
    run()
