# Pub/Sub event bus (MM-119, ADR-0012): the GCP counterpart to the Kafka
# topics, same names so the app's topic settings don't change. Free tier:
# 10 GB/month -- the demo's price + event traffic is a few MB.
#
# The consumer subscriptions (below) push to the API on Cloud Run (MM-124).

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

# Event Agent subscriptions (MM-120). They push to the API on Cloud Run since
# MM-124 (`POST /internal/pubsub/push`, MM-121); locally the emulator's own
# subscriptions are pulled by `python -m streaming.pubsub_worker` instead.
# Ordering is on (it can't be changed after creation), so one ticker's ticks
# are handled in publish order.
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

  # MM-124: Pub/Sub pushes each message to the API, signed as mm-invoker-sa.
  # 2xx acks; anything else is retried, then dead-lettered.
  push_config {
    push_endpoint = "${local.api_base_url}/internal/pubsub/push"
    oidc_token {
      service_account_email = google_service_account.component["invoker"].email
      audience              = local.api_base_url
    }
  }

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

# Impact consumer (MM-121): impact sets -> margin-call runs, one per affected
# counterparty, exactly once (claim row in processed_events). A run calls the
# LLM and pauses at the approval gate, so the ack deadline is the 10-minute
# maximum rather than the Event Agent's 60 s.
resource "google_pubsub_subscription" "orchestrator_impact" {
  name                       = "orchestrator.market.impact"
  topic                      = google_pubsub_topic.events["market.impact"].id
  enable_message_ordering    = true
  ack_deadline_seconds       = 600
  message_retention_duration = "86400s"

  # MM-124: Pub/Sub pushes each message to the API, signed as mm-invoker-sa.
  # 2xx acks; anything else is retried, then dead-lettered.
  push_config {
    push_endpoint = "${local.api_base_url}/internal/pubsub/push"
    oidc_token {
      service_account_email = google_service_account.component["invoker"].email
      audience              = local.api_base_url
    }
  }

  expiration_policy {
    ttl = ""
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

resource "google_pubsub_subscription_iam_member" "orchestrator_impact" {
  for_each = {
    consumer   = "serviceAccount:${google_service_account.component["events"].email}"
    deadletter = local.pubsub_agent
  }

  subscription = google_pubsub_subscription.orchestrator_impact.name
  role         = "roles/pubsub.subscriber"
  member       = each.value
}

# Push authentication (MM-121): Pub/Sub signs each push request with an OIDC
# token for mm-invoker-sa; the API accepts only that identity
# (INTERNAL_CALLER_SERVICE_ACCOUNT). The push_config itself is added in G5.
resource "google_service_account_iam_member" "pubsub_signs_as_invoker" {
  service_account_id = google_service_account.component["invoker"].name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = local.pubsub_agent
}
