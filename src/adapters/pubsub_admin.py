"""Create the event topics (MM-119) and the consumer subscriptions
(MM-120/121) on a Pub/Sub emulator. Real GCP topics and subscriptions are
Terraform-managed (infra/gcp/pubsub.tf); this is for local dev and tests:

    PUBSUB_EMULATOR_HOST=localhost:8085 python -m adapters.pubsub_admin
"""

import os
from typing import Any

from config.settings import Settings, get_settings


def event_topics(settings: Settings) -> list[str]:
    return [
        settings.kafka_topic_prices,
        settings.kafka_topic_events,
        settings.kafka_topic_impact,
        settings.kafka_topic_calls,
        settings.kafka_topic_dead_letter,
    ]


def consumer_subscriptions(settings: Settings) -> dict[str, str]:
    """Topic -> subscription for each consumer; same names as Terraform
    (infra/gcp/pubsub.tf). The Event Agent reads prices and events; the
    impact consumer (MM-121) turns impact sets into margin-call runs."""
    return {
        settings.kafka_topic_prices: f"event-agent.{settings.kafka_topic_prices}",
        settings.kafka_topic_events: f"event-agent.{settings.kafka_topic_events}",
        settings.kafka_topic_impact: f"orchestrator.{settings.kafka_topic_impact}",
    }


def topic_for_subscription(settings: Settings, subscription: str) -> str | None:
    """Accepts a bare name or a full `projects/<p>/subscriptions/<name>` path."""
    name = subscription.rsplit("/", 1)[-1]
    return {sub: topic for topic, sub in consumer_subscriptions(settings).items()}.get(name)


def ensure_topics(project_id: str, topics: list[str], publisher: Any | None = None) -> list[str]:
    """Create any missing topics; returns the ones created."""
    from google.api_core.exceptions import AlreadyExists
    from google.cloud.pubsub_v1 import PublisherClient

    publisher = publisher or PublisherClient()
    created = []
    for topic in topics:
        try:
            publisher.create_topic(name=publisher.topic_path(project_id, topic))
            created.append(topic)
        except AlreadyExists:
            pass
    return created


def ensure_subscriptions(
    project_id: str, subscriptions: dict[str, str], subscriber: Any | None = None
) -> list[str]:
    """Create any missing consumer subscriptions (topic -> name; ordered,
    like Terraform's); returns the ones created."""
    from google.api_core.exceptions import AlreadyExists
    from google.cloud.pubsub_v1 import PublisherClient, SubscriberClient

    subscriber = subscriber or SubscriberClient()
    created = []
    for topic, name in subscriptions.items():
        try:
            subscriber.create_subscription(
                request={
                    "name": subscriber.subscription_path(project_id, name),
                    "topic": PublisherClient.topic_path(project_id, topic),
                    "enable_message_ordering": True,
                    "ack_deadline_seconds": 600,
                }
            )
            created.append(name)
        except AlreadyExists:
            pass
    return created


def main() -> None:
    if not os.environ.get("PUBSUB_EMULATOR_HOST"):
        raise SystemExit("Set PUBSUB_EMULATOR_HOST -- real topics are managed by Terraform")
    settings = get_settings()
    project = settings.gcp_project_id or "marginmaestro-demo"
    created = ensure_topics(project, event_topics(settings))
    created += ensure_subscriptions(project, consumer_subscriptions(settings))
    print(f"Emulator topics ready in {project}; created: {created or 'none (already there)'}")


if __name__ == "__main__":
    main()
