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

# Daily end-of-day load (MM-124): 16:30 New York on weekdays, after the
# close, appends official daily closes (with a short back-fill for days the
# app was off) to price_history and refreshes FRED reference rates -- the
# "previous close" the shock check compares against, and the history behind
# initial-margin volatility and the charts. Same on/off switch.
resource "google_cloud_scheduler_job" "eod_prices" {
  name        = "eod-prices"
  region      = var.region
  description = "Load official daily closes and reference rates after the US close"
  schedule    = "30 16 * * 1-5"
  time_zone   = "America/New_York"
  paused      = !var.demo_online

  attempt_deadline = "300s"

  retry_config {
    retry_count          = 2
    min_backoff_duration = "60s"
  }

  http_target {
    http_method = "POST"
    uri         = "${local.api_base_url}/internal/prices/eod"

    oidc_token {
      service_account_email = google_service_account.component["invoker"].email
      audience              = local.api_base_url
    }
  }

  depends_on = [google_project_service.cloudscheduler]
}

# Daily margin run (MM-125, Phase G5b): 16:45 New York on weekdays, after
# eod-prices (16:30) has loaded the official closes. Every counterparty is
# evaluated; standing breaches raise calls (each paused at the approval gate)
# and an open call is re-evaluated in place, never doubled. Intraday events
# raise calls only past the materiality gate, so this is where standing
# exposure is called. Once a day per counterparty: a retry skips the ones
# already done, and a 503 (another trigger holds a counterparty) is retried.
# Same on/off switch. The third job, so still inside the free tier.
resource "google_cloud_scheduler_job" "daily_margin_run" {
  name        = "daily-margin-run"
  region      = var.region
  description = "Evaluate every counterparty after the EOD price load and call standing breaches"
  schedule    = "45 16 * * 1-5"
  time_zone   = "America/New_York"
  paused      = !var.demo_online

  attempt_deadline = "600s" # the API's request timeout; one CSA extraction per counterparty

  retry_config {
    retry_count          = 2
    min_backoff_duration = "60s"
  }

  http_target {
    http_method = "POST"
    uri         = "${local.api_base_url}/internal/margin/daily-run"

    oidc_token {
      service_account_email = google_service_account.component["invoker"].email
      audience              = local.api_base_url
    }
  }

  depends_on = [google_project_service.cloudscheduler]
}
