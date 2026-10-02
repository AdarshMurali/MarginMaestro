# Pub/Sub event bus (MM-119, ADR-0012): the GCP counterpart to the Kafka
# topics, same names so the app's topic settings don't change. Free tier:
# 10 GB/month -- the demo's price + event traffic is a few MB.
#
# The Event Agent's subscriptions (below) are pull until G5, when they get a
# push endpoint on Cloud Run once the API has a URL.

locals {
  event_topics = [
    "market.prices", # live price ticks (MM-120), ordering key = ticker
    "market.events", # market events (shocks, news-driven), ordering key = event id
    "market.impact", # impact sets -> margin-call evaluation, ordering key = event id
    "margin.calls",  # margin-call lifecycle events
  ]
}

resource "google_project_service" "pubsub" {
  service            = "pubsub.googleapis.com"
  disable_on_destroy = false
}

resource "google_pubsub_topic" "events" {
  for_each = toset(local.event_topics)

  name                       = each.value
  message_retention_duration = "86400s" # replay window for a day (seek)

  depends_on = [google_project_service.pubsub]
}

resource "google_pubsub_topic" "dead_letter" {
  name                       = "market.dead-letter"
  message_retention_duration = "604800s" # keep poison messages a week for inspection

  depends_on = [google_project_service.pubsub]
}

# Who publishes: the API (price refresh, simulate) and the event consumers
# (impact sets). Granted per topic, not project-wide.
resource "google_pubsub_topic_iam_member" "publishers" {
  for_each = {
    for pair in setproduct(local.event_topics, ["api", "events"]) :
    "${pair[0]}:${pair[1]}" => { topic = pair[0], account = pair[1] }
  }

  topic  = google_pubsub_topic.events[each.value.topic].name
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${google_service_account.component[each.value.account].email}"
}

# Event Agent subscriptions (MM-120). Pull for now -- the local listener
# (`python -m streaming.pubsub_event_agent`) drains them; G5 adds a
# push_config pointing at the Event Agent on Cloud Run (MM-121), on these same
# subscriptions. Ordering is on (it can't be changed after creation), so one
# ticker's ticks are handled in publish order.
#
# The app dead-letters a message itself after 3 failed attempts and acks it;
# the subscription's own dead-letter policy is the backstop for a consumer
# that crashes or nacks before it can do that.
locals {
  event_agent_topics = ["market.prices", "market.events"]
  pubsub_agent       = "serviceAccount:service-${data.google_project.this.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

resource "google_pubsub_subscription" "event_agent" {
  for_each = toset(local.event_agent_topics)

  name                       = "event-agent.${each.value}"
  topic                      = google_pubsub_topic.events[each.value].id
  enable_message_ordering    = true
  ack_deadline_seconds       = 60
  message_retention_duration = "86400s" # an unread tick is stale after a day

  expiration_policy {
    ttl = "" # never expire, even while nothing is pulling (e.g. demo offline)
  }

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "300s"
  }

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.dead_letter.id
    max_delivery_attempts = 5
  }
}

resource "google_pubsub_subscription_iam_member" "event_agent_subscriber" {
  for_each = google_pubsub_subscription.event_agent

  subscription = each.value.name
  role         = "roles/pubsub.subscriber"
  member       = "serviceAccount:${google_service_account.component["events"].email}"
}

# Pub/Sub's own service agent forwards undeliverable messages, so it needs to
# publish to the dead-letter topic and to ack on the source subscriptions.
resource "google_pubsub_topic_iam_member" "dead_letter_forwarder" {
  topic  = google_pubsub_topic.dead_letter.name
  role   = "roles/pubsub.publisher"
  member = local.pubsub_agent
}

resource "google_pubsub_subscription_iam_member" "dead_letter_ack" {
  for_each = google_pubsub_subscription.event_agent

  subscription = each.value.name
  role         = "roles/pubsub.subscriber"
  member       = local.pubsub_agent
}
