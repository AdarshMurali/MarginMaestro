# Tableau Desktop on the MarginMaestro warehouse

A guide for Tableau Desktop (free edition, workbooks saved locally) on the BigQuery warehouse. It mirrors the five reports of the app's `/reports` page. See `docs/warehouse/README.md` for the data model.

## 1. Access (once, in Terraform)

Your Google account needs:

- `roles/bigquery.dataViewer` on the dataset `marginmaestro_analytics`;
- `roles/bigquery.jobUser` on the project `marginmaestro-demo` (to run the extract query);
- a row access policy that lets you see rows, and optionally unmasked confidential columns.

All three come from one Terraform variable. In `infra/gcp/terraform.tfvars` (gitignored; the repo is public, so no emails in code):

```hcl
warehouse_readers = ["user:you@example.com"]
# optional: see collateral, headroom and market values unmasked
warehouse_unmasked_readers = ["user:you@example.com"]
```

`terraform apply` grants dataViewer + jobUser, adds you to each table's firm-wide (`TRUE`) row access policy, and gives you Masked Reader on the confidential columns (or Fine-Grained Reader if you are in `warehouse_unmasked_readers`). Without the unmasked grant, `collateral_held`, `headroom`, `coverage_ratio` and the market values read as 0.

## 2. Connect

1. Tableau Desktop → **Connect → To a Server → Google BigQuery**.
2. **Sign in with your own Google account** (OAuth in the browser). Do not create or download a service-account key.
3. Billing project: `marginmaestro-demo`. Project: `marginmaestro-demo`. Dataset: `marginmaestro_analytics`.
4. Drag in **only the report tables**:
   - `rpt_counterparty_daily` (reports 1, 2, 5)
   - `rpt_concentration` (report 3)
   - `rpt_margin_call` (report 4)
   - optionally `dim_counterparty` (names, type, country) and `dim_date` (calendar), joined on `book` + `counterparty_id` / the date.

   **Never** `fact_position_daily` (63M rows, 5.4 GB) or the other `fact_*` tables: they need a partition filter and every refresh would scan gigabytes.

## 3. Extract, not live (cost guardrail)

Set the connection to **Extract** (top right of the Data Source page), not Live.

- Add an **extract filter** on `book` (and, for `rpt_counterparty_daily`, on `as_of_date` if you only need recent years) before creating the extract.
- Tableau runs one query per table to build the `.hyper` file; every chart afterwards runs locally. Sizes: `rpt_counterparty_daily` ~1.26M rows (~140 MB scanned), `rpt_concentration` ~3M rows (~225 MB), `rpt_margin_call` ~127k rows (~10 MB) — well inside the 1 TiB monthly free tier, even refreshed daily.
- Refresh the extract by hand (Data → Extract → Refresh) after the daily load (~16:45 New York on weekdays). The simulated book never changes, so one extract of it is enough.

## 4. Five worksheets (and one dashboard)

Each mirrors a report on the app's `/reports` page. Put a `book` filter (live / historical-sim) on every sheet and apply it to all worksheets using this data source.

### 1. Exposure & threshold headroom (`rpt_counterparty_daily`)
- Columns: `as_of_date` (continuous, day). Rows: `SUM(exposure)`, `SUM(threshold)`, `SUM(headroom)` as a dual/combined line chart.
- Tooltip: `COUNTD(counterparty_id)`, `SUM(IIF(breached,1,0))` (counterparties in breach).
- Filters: `book`, `tier`, `as_of_date` range.

### 2. Collateral adequacy (`rpt_counterparty_daily`)
- Filter `as_of_date` to the latest day (a "Top 1 by MAX(as_of_date)" filter, or a relative-date filter).
- Calculated field `Coverage bucket`:
  `IF [required_support] = 0 THEN "no requirement" ELSEIF [coverage_ratio] >= 1.2 THEN "120% or more" ELSEIF [coverage_ratio] >= 1 THEN "100-120%" ELSEIF [coverage_ratio] >= 0.8 THEN "80-100%" ELSE "under 80%" END`
- Bar chart: `Coverage bucket` x `COUNTD(counterparty_id)`; a second table sorted ascending by `headroom` (top 15): counterparty, tier, required support, collateral held, coverage.

### 3. Concentration risk (`rpt_concentration`)
- Filter `month_start` to the latest month.
- Horizontal bar: `sector` x `SUM(gross_market_value)`, colour by `SUM(net_market_value)` (diverging).
- Treemap: `ticker` sized by `SUM(gross_market_value)` (Top 15 filter); a small bar by `asset_class`.

### 4. Margin-call performance (`rpt_margin_call`)
- Columns: `MONTH(raised_date)`. Rows: `COUNT(call_id)` stacked by `sla_outcome` (null = open).
- Second axis or table: `SUM(call_amount)`, `AVG(approval_minutes)`, `PERCENTILE(approval_minutes, 0.9)`, `SUM(IIF(escalated,1,0))`.
- Filters: `book`, `tier`, `trigger_type`.

### 5. Stress & backtest (`rpt_counterparty_daily`)
- Calls per month: `MONTH(as_of_date)` x `SUM(IIF(call_raised,1,0))` (bars) with `MAX(vix)` on a dual axis (line).
- Heaviest days: a table of `as_of_date` with `SUM(IIF(call_raised, call_due, 0))`, sorted descending, Top 20 — e.g. the 2022 drawdowns stand out in the simulated book.

### Dashboard
One dashboard with the five sheets in a 2-2-1 grid, the `book` filter shown once at the top and applied to all sheets. Save the workbook as a packaged `.twbx` (extract included) on your machine.

## Notes

- Numbers are computed by MarginMaestro's calc engine and loaded by the backfill / the daily load; Tableau only aggregates them, exactly like the `/reports` page.
- The simulated book is synthetic (1,000 `SIM-nnnn` counterparties over real closes, with survivorship bias): see the README's "Simplifications".
- A scoped analyst account (`warehouse_scoped_readers`) sees only its live counterparties and never the simulated book.
