"""Routes one Pub/Sub message to its consumer (MM-121). Shared by the pull
worker (`streaming.pubsub_worker`, local) and the push endpoint
(`POST /internal/pubsub/push`, Cloud Run from G5), so both run identical code.

- `market.prices` / `market.events` -> Event Agent (retries, then dead-letters
  itself and returns normally).
- `market.impact` -> impact consumer: one margin-call run per counterparty,
  exactly once.

Returning normally means "ack". Raising means "redeliver" (pull: no ack; push:
a 5xx), and Pub/Sub's dead-letter policy takes over after 5 attempts.
"""

from collections.abc import Callable

from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.orm import Session, sessionmaker

from agents.orchestrator import build_orchestrator_graph
from config.settings import Settings
from ports.event_bus import EventBus
from streaming.event_agent import _handle_with_retry
from streaming.impact_consumer import handle_impact
from streaming.inbound import PubSubInbound, decode
from streaming.market_feed import get_market_feed
from streaming.schemas import ImpactSet


def live_graph_factory(
    settings: Settings, session_factory: sessionmaker[Session]
) -> Callable[[], CompiledStateGraph]:
    """Runs price off the configured feed (MARKET_FEED_MODE), not a shocked one."""
    return lambda: build_orchestrator_graph(
        session_factory=session_factory, market_feed=get_market_feed(settings), settings=settings
    )


def dispatch(
    inbound: PubSubInbound,
    settings: Settings,
    session_factory: sessionmaker[Session],
    producer: EventBus,
    graph_factory: Callable[[], CompiledStateGraph] | None = None,
) -> None:
    if inbound.topic() == settings.kafka_topic_impact:
        handle_impact(
            decode(inbound, ImpactSet),
            session_factory,
            graph_factory or live_graph_factory(settings, session_factory),
        )
        return
    _handle_with_retry(inbound, producer, settings, session_factory)
