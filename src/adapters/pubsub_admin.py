"""Create the event topics (MM-119) and the Event Agent's subscriptions
(MM-120) on a Pub/Sub emulator. Real GCP topics and subscriptions are
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


def event_agent_topics(settings: Settings) -> list[str]:
    """The topics the Event Agent consumes."""
    return [settings.kafka_topic_prices, settings.kafka_topic_events]


def event_agent_subscription(topic: str) -> str:
    """Same naming as Terraform's google_pubsub_subscription.event_agent."""
    return f"event-agent.{topic}"


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
    project_id: str, topics: list[str], subscriber: Any | None = None
) -> list[str]:
    """Create any missing Event Agent subscriptions (ordered, like Terraform's);
    returns the ones created."""
    from google.api_core.exceptions import AlreadyExists
    from google.cloud.pubsub_v1 import PublisherClient, SubscriberClient

    subscriber = subscriber or SubscriberClient()
    created = []
    for topic in topics:
        name = event_agent_subscription(topic)
        try:
            subscriber.create_subscription(
                request={
                    "name": subscriber.subscription_path(project_id, name),
                    "topic": PublisherClient.topic_path(project_id, topic),
                    "enable_message_ordering": True,
                    "ack_deadline_seconds": 60,
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
    created += ensure_subscriptions(project, event_agent_topics(settings))
    print(f"Emulator topics ready in {project}; created: {created or 'none (already there)'}")


if __name__ == "__main__":
    main()
