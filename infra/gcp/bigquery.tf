# BigQuery finance warehouse (Phase G7, MM-139 / MM-142, ADR-0013).
#
# Dataset `marginmaestro_analytics` (us-central1): a star schema of facts,
# dimensions and pre-aggregated report tables. The table schemas are NOT
# written here: src/warehouse/schemas.py is the source of truth and renders
# bigquery_schemas/*.json (`python -m warehouse.schemas --write`; a unit test
# fails if they drift). Column classes come from docs/data_catalog.yaml
# (`warehouse_tables`): every confidential column gets the `confidential`
# policy tag, which masks it for anyone without fine-grained read access.
#
# Access model (mirrors Cloud SQL row-level security, MM-106):
#   - mm-api-sa and var.warehouse_loaders: write (dataEditor), run jobs, read
#     unmasked, and see every row (a TRUE row access policy is required for
#     DML on a table that has row access policies).
#   - var.warehouse_readers (e.g. the Tableau user, firm-wide): read every
#     row; confidential columns masked unless also in
#     var.warehouse_unmasked_readers.
#   - var.warehouse_scoped_readers (member -> counterparty ids, the BigQuery
#     mirror of user_counterparty_access): read the live book's rows for
#     those counterparties only; the simulated book is firm-wide only.
#   Anyone not named in a row access policy sees no rows of that table.
#
# Cost ($0 target, ADR-0017):
#   - Storage: ~6 GB logical after the full backfill (fact_position_daily
#     ~5.4 GB) -- inside the 10 GiB/month free tier. Logical billing, so the
#     time-travel copies left by partition replaces are not billed.
#   - Queries: every query the app issues sets maximum_bytes_billed; the
#     backfill's report refreshes scan ~5 GB once, a daily live load a few
#     MB, a report page view <= 75 MB (cached 10 minutes) -- far inside the
#     1 TiB/month free tier.
#   - Loads are batch load jobs (free); no streaming inserts.
#   - Policy tags, data policies (masking) and row access policies: no charge
#     (masking is available with on-demand pricing).
#   - The optional 4th Cloud Scheduler job (var.warehouse_load_job) is the one
#     paid item: $0.10/month (3 jobs are free per billing account). Off by
#     default -- the daily margin run triggers the load instead.

locals {
  warehouse_dataset = "marginmaestro_analytics"
  warehouse_tables  = jsondecode(file("${path.module}/bigquery_schemas/tables.json"))
  warehouse_specs = {
    for name in local.warehouse_tables :
    name => jsondecode(file("${path.module}/bigquery_schemas/${name}.json"))
  }
  # Confidential columns per table, from the catalog (dataplex.tf's local.catalog).
  warehouse_confidential = {
    for name, table in local.catalog.warehouse_tables :
    name => [for column, entry in table.columns : column if entry.class == "confidential"]
  }
  warehouse_row_tables = [for name, spec in local.warehouse_specs : name if spec.has_counterparty]

  warehouse_writers = concat(
    ["serviceAccount:${google_service_account.component["api"].email}"],
    var.warehouse_loaders,
  )
  warehouse_job_users = toset(concat(
    local.warehouse_writers,
    var.warehouse_readers,
    keys(var.warehouse_scoped_readers),
  ))
  warehouse_scoped_policies = {
    for pair in setproduct(local.warehouse_row_tables, keys(var.warehouse_scoped_readers)) :
    "${pair[0]}|${pair[1]}" => { table = pair[0], member = pair[1] }
  }
}

resource "google_project_service" "warehouse" {
  for_each = toset([
    "bigquery.googleapis.com",
    "bigquerydatapolicy.googleapis.com",
    "datacatalog.googleapis.com",
  ])

  service            = each.value
  disable_on_destroy = false
}

resource "google_bigquery_dataset" "analytics" {
  dataset_id            = local.warehouse_dataset
  location              = var.region
  friendly_name         = "MarginMaestro analytics"
  description           = "Finance warehouse: daily exposure, positions, margin calls and prices for the live book and the simulated historical book (ADR-0013)."
  max_time_travel_hours = 48
  # No default table expiration: the warehouse is the long-term history.

  labels = {
    component  = "warehouse"
    data-class = "confidential"
  }

  depends_on = [google_project_service.warehouse]
}

# --- column-level security: one taxonomy, one policy tag, one masking rule -----

resource "google_data_catalog_taxonomy" "classification" {
  region                 = var.region
  display_name           = "MarginMaestro classification"
  description            = "Column classes from docs/data_catalog.yaml (ADR-0015)."
  activated_policy_types = ["FINE_GRAINED_ACCESS_CONTROL"]

  depends_on = [google_project_service.warehouse]
}

resource "google_data_catalog_policy_tag" "confidential" {
  taxonomy     = google_data_catalog_taxonomy.classification.id
  display_name = "confidential"
  description  = "Quantities, market values, collateral and legal names: masked unless the reader has fine-grained read access."
}

resource "google_bigquery_datapolicy_data_policy" "mask_confidential" {
  location         = var.region
  data_policy_id   = "mask_confidential"
  policy_tag       = google_data_catalog_policy_tag.confidential.name
  data_policy_type = "DATA_MASKING_POLICY"

  data_masking_policy {
    predefined_expression = "DEFAULT_MASKING_VALUE" # 0 for numbers, '' for strings
  }
}

# --- tables ------------------------------------------------------------------------

resource "google_bigquery_table" "warehouse" {
  for_each = local.warehouse_specs

  dataset_id               = google_bigquery_dataset.analytics.dataset_id
  table_id                 = each.key
  description              = each.value.description
  deletion_protection      = true
  require_partition_filter = each.value.require_partition_filter
  clustering               = length(each.value.clustering) > 0 ? each.value.clustering : null

  labels = {
    component = "warehouse"
    kind      = each.value.kind
  }

  schema = jsonencode([
    for field in each.value.schema : merge(
      field,
      contains(lookup(local.warehouse_confidential, each.key, []), field.name)
      ? { policyTags = { names = [google_data_catalog_policy_tag.confidential.name] } }
      : {}
    )
  ])

  dynamic "time_partitioning" {
    for_each = contains(["DAY", "MONTH"], coalesce(each.value.partition_type, "NONE")) ? [1] : []
    content {
      type  = each.value.partition_type
      field = each.value.partition_column
    }
  }

  dynamic "range_partitioning" {
    for_each = each.value.partition_type == "BOOK" ? [1] : []
    content {
      field = each.value.partition_column
      range {
        start    = 0
        end      = 2
        interval = 1
      }
    }
  }
}

# --- IAM ------------------------------------------------------------------------------

resource "google_bigquery_dataset_iam_member" "writers" {
  for_each = toset(local.warehouse_writers)

  dataset_id = google_bigquery_dataset.analytics.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = each.value
}

resource "google_bigquery_dataset_iam_member" "readers" {
  for_each = toset(concat(var.warehouse_readers, keys(var.warehouse_scoped_readers)))

  dataset_id = google_bigquery_dataset.analytics.dataset_id
  role       = "roles/bigquery.dataViewer"
  member     = each.value
}

resource "google_project_iam_member" "warehouse_job_user" {
  for_each = local.warehouse_job_users

  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = each.value
}

resource "google_data_catalog_policy_tag_iam_member" "unmasked" {
  for_each = toset(concat(local.warehouse_writers, var.warehouse_unmasked_readers))

  policy_tag = google_data_catalog_policy_tag.confidential.name
  role       = "roles/datacatalog.categoryFineGrainedReader"
  member     = each.value
}

resource "google_bigquery_datapolicy_data_policy_iam_member" "masked" {
  for_each = toset(concat(var.warehouse_readers, keys(var.warehouse_scoped_readers)))

  project        = var.project_id
  location       = var.region
  data_policy_id = google_bigquery_datapolicy_data_policy.mask_confidential.data_policy_id
  role           = "roles/bigquerydatapolicy.maskedReader"
  member         = each.value
}

# --- row access policies (mirror of Cloud SQL RLS) --------------------------------------

resource "google_bigquery_row_access_policy" "firm_wide" {
  for_each = toset(local.warehouse_row_tables)

  dataset_id       = google_bigquery_dataset.analytics.dataset_id
  table_id         = google_bigquery_table.warehouse[each.value].table_id
  policy_id        = "firm_wide"
  filter_predicate = "TRUE"
  grantees         = concat(local.warehouse_writers, var.warehouse_readers)
}

resource "google_bigquery_row_access_policy" "scoped" {
  for_each = local.warehouse_scoped_policies

  dataset_id = google_bigquery_dataset.analytics.dataset_id
  table_id   = google_bigquery_table.warehouse[each.value.table].table_id
  # Policy ids allow letters, digits and underscores only.
  policy_id = "scoped_${substr(sha256(each.value.member), 0, 16)}"
  filter_predicate = format(
    "book = 'live' AND counterparty_id IN (%s)",
    join(", ", [for cp in var.warehouse_scoped_readers[each.value.member] : "'${cp}'"]),
  )
  grantees = [each.value.member]
}

# --- optional dedicated load job (paid: the 4th Cloud Scheduler job) ------------

resource "google_cloud_scheduler_job" "warehouse_daily_load" {
  count = var.warehouse_load_job ? 1 : 0

  name        = "warehouse-daily-load"
  region      = var.region
  description = "Load the live book's end-of-day state into BigQuery (MM-141)"
  schedule    = "15 17 * * 1-5"
  time_zone   = "America/New_York"
  paused      = !var.demo_online

  attempt_deadline = "300s"

  retry_config {
    retry_count          = 2
    min_backoff_duration = "60s"
  }

  http_target {
    http_method = "POST"
    uri         = "${local.api_base_url}/internal/warehouse/daily-load"

    oidc_token {
      service_account_email = google_service_account.component["invoker"].email
      audience              = local.api_base_url
    }
  }

  depends_on = [google_project_service.cloudscheduler]
}

output "warehouse_dataset" {
  description = "BigQuery dataset of the finance warehouse (MM-139)"
  value       = "${var.project_id}.${google_bigquery_dataset.analytics.dataset_id}"
}
