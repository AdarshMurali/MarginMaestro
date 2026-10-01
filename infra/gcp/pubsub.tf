# Pub/Sub event bus (MM-119, ADR-0012): the GCP counterpart to the Kafka
# topics, same names so the app's topic settings don't change. Free tier:
# 10 GB/month -- the demo's price + event traffic is a few MB.
#
# Push subscriptions (to the Event Agent on Cloud Run) and their dead-letter
# policies are created in G5, once the API has a URL.

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
