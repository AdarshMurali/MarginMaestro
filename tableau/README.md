# MarginMaestro — Tableau workbook guide

Three extracts (no joins): **CD** = `rpt_counterparty_daily`, **CC** = `rpt_concentration`, **MC** = `rpt_margin_call`.
Add a `book` filter to every sheet (default `historical-sim`; `live` = the 8 real counterparties). Format currency as USD.

## Worksheets

| # | Sheet | Source | Build | Shows |
|---|---|---|---|---|
| 1 | **Exposure vs Threshold** | CD | Line: `as_of_date` (week) × SUM(`exposure`) and SUM(`threshold`) (dual axis, synced). Filter `tier`. | When the book's exposure crosses its thresholds. |
| 2 | **Headroom Heatmap** | CD | Rows `counterparty_id` (top 25 by lowest AVG(`headroom`)), Columns `as_of_date` (month), Color AVG(`headroom`) diverging red↔green, centre 0. | Which counterparties live close to a call. |
| 3 | **Collateral Coverage** | CD | Line: `as_of_date` (month) × AVG(`coverage_ratio`); reference line at 1.0. Color `tier`. | Whether collateral keeps up with required support. |
| 4 | **Stress Days** | CD | Bars: `as_of_date` (day) × SUM(`call_due`), top 15 days. Tooltip: AVG(`vix`), COUNT where `call_raised`. | The worst historical days and the VIX behind them. |
| 5 | **VIX vs Calls** | CD | Scatter per day: AVG(`vix`) × SUM(`call_due`); size = COUNTD(`counterparty_id`) where `breached`. | Volatility drives margin calls. |
| 6 | **Sector Concentration** | CC | Treemap: `sector` → `ticker`, size SUM(`gross_market_value`) for the latest `month_start`. | Where the book's risk is concentrated. |
| 7 | **Asset-Class Mix** | CC | Stacked area: `month_start` × SUM(`gross_market_value`), color `asset_class`. | How the mix shifts over time. |
| 8 | **Calls per Month** | MC | Bars: MONTH(`raised_date`) × COUNT(`call_id`), color `trigger_type`; line SUM(`call_amount`) on dual axis. | Call volume and value. |
| 9 | **Approval & SLA** | MC | Box plot of `approval_minutes` by `tier`; beside it, % of calls by `sla_outcome` (met / breached) as a 100% bar. | Turnaround and SLA performance. |
| 10 | **KPI Tiles** | CD + MC | Text sheets: latest SUM(`exposure`), AVG(`coverage_ratio`), COUNT(`call_id`), % `escalated`. | Headline numbers. |

## Dashboards

1. **Risk Overview** — KPI Tiles (top), Exposure vs Threshold, Headroom Heatmap, Collateral Coverage. Filters: `book`, `tier`, date range.
2. **Concentration & Stress** — Sector Concentration, Asset-Class Mix, Stress Days, VIX vs Calls.
3. **Margin-Call Operations** — Calls per Month, Approval & SLA; click a month to filter (dashboard action).

Use a consistent palette (red = breach/escalation, green = healthy). Save the workbook as `.twbx` here; export screenshots to `tableau/screenshots/`.
