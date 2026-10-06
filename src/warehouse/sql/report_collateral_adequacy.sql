-- Report 2, collateral adequacy (MM-142): each counterparty on the latest day
-- in the range, with its coverage bucket.
-- Reads rpt_counterparty_daily only, pruned to the date range: 8 columns,
-- ~85 logical bytes/row (~11 MB for a quarter of the simulated book).
WITH scoped AS (
  SELECT *
  FROM rpt_counterparty_daily
  WHERE as_of_date BETWEEN @start_date AND @end_date
    AND book = @book
    AND (@scope_all OR counterparty_id IN UNNEST(@counterparty_ids))
)
SELECT
  as_of_date,
  counterparty_id,
  tier,
  required_support,
  collateral_held,
  coverage_ratio,
  headroom,
  CASE
    WHEN required_support = 0 THEN 'no requirement'
    WHEN coverage_ratio >= 1.2 THEN '120% or more'
    WHEN coverage_ratio >= 1.0 THEN '100-120%'
    WHEN coverage_ratio >= 0.8 THEN '80-100%'
    ELSE 'under 80%'
  END AS coverage_bucket
FROM scoped
WHERE as_of_date = (SELECT MAX(as_of_date) FROM scoped)
ORDER BY headroom ASC
