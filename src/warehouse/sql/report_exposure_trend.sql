-- Report 1, exposure & threshold-headroom trend (MM-142): one point per day.
-- Reads rpt_counterparty_daily only, pruned to the date range: 6 columns,
-- ~60 logical bytes/row (~75 MB for all five years of the simulated book).
-- Scope: @scope_all, or only @counterparty_ids (the caller's RLS scope).
SELECT
  as_of_date,
  COUNT(*) AS counterparties,
  SUM(exposure) AS exposure,
  SUM(threshold) AS threshold,
  SUM(headroom) AS headroom,
  COUNTIF(breached) AS breached,
  COUNTIF(headroom < 0) AS shortfalls
FROM rpt_counterparty_daily
WHERE as_of_date BETWEEN @start_date AND @end_date
  AND book = @book
  AND (@scope_all OR counterparty_id IN UNNEST(@counterparty_ids))
GROUP BY as_of_date
ORDER BY as_of_date
