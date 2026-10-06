-- MM-142: refresh rpt_counterparty_daily (reports 1, 2 and 5) for one date range.
-- Idempotent: drops the range's partitions (whole-partition DELETE, 0 bytes),
-- then re-inserts them from fact_daily_exposure.
-- Scans: fact_daily_exposure, the range's partitions only, 13 columns
-- (~115 logical bytes/row: ~115 KB per trading day of the simulated book,
-- ~145 MB for all five years); dim_counterparty (3 columns, ~40 KB).
DELETE FROM rpt_counterparty_daily
WHERE as_of_date BETWEEN @start_date AND @end_date;

INSERT INTO rpt_counterparty_daily (
  as_of_date, book, counterparty_id, tier, exposure, threshold, headroom,
  required_support, collateral_held, coverage_ratio, breached, call_raised, call_due, vix
)
SELECT
  e.as_of_date,
  e.book,
  e.counterparty_id,
  COALESCE(c.tier, 'standard') AS tier,
  e.exposure,
  e.threshold,
  e.headroom,
  e.required_support,
  e.collateral_held,
  SAFE_DIVIDE(e.collateral_held, NULLIF(e.required_support, 0)) AS coverage_ratio,
  e.breached,
  e.call_raised,
  e.call_due,
  e.vix
FROM fact_daily_exposure AS e
LEFT JOIN dim_counterparty AS c
  ON c.book = e.book AND c.counterparty_id = e.counterparty_id
WHERE e.as_of_date BETWEEN @start_date AND @end_date;
