# Live price refresh (MM-124, MM-G44): every 5 minutes on weekdays,
# 09:00-15:55 New York time, Cloud Scheduler calls the API's
# /internal/prices/refresh, which publishes one tick per ticker to
# market.prices. Market hours are enforced by the cron, not code; a holiday
# run only re-publishes the last price, which the Event Agent skips.
#
# Paused whenever demo_online = false, so a stopped Cloud SQL never piles up
# failing refreshes -- the one switch from MM-120. Free: 3 jobs per billing
# account.

resource "google_project_service" "cloudscheduler" {
  service            = "cloudscheduler.googleapis.com"
  disable_on_destroy = false
}

resource "google_cloud_scheduler_job" "price_refresh" {
  name        = "price-refresh"
  region      = var.region
  description = "Publish live prices to market.prices every 5 minutes in US market hours"
  schedule    = "*/5 9-15 * * 1-5"
  time_zone   = "America/New_York"
  paused      = !var.demo_online

  attempt_deadline = "120s"

  retry_config {
    retry_count = 0 # the next run is 5 minutes away anyway
  }

  http_target {
    http_method = "POST"
    uri         = "${local.api_base_url}/internal/prices/refresh"

    oidc_token {
      service_account_email = google_service_account.component["invoker"].email
      audience              = local.api_base_url
    }
  }

  depends_on = [google_project_service.cloudscheduler]
}
