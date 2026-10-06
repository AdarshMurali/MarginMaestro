-- Report 5a, stress / backtest (MM-142): the days that triggered the most
-- margin calls by amount, with that day's VIX.
-- Reads rpt_counterparty_daily only, pruned to the range: 7 columns,
-- ~45 logical bytes/row (~57 MB for all five years of the simulated book).
SELECT
  as_of_date,
  COUNTIF(call_raised) AS calls_raised,
  SUM(IF(call_raised, call_due, 0)) AS call_amount,
  COUNTIF(breached) AS breached,
  MAX(vix) AS vix
FROM rpt_counterparty_daily
WHERE as_of_date BETWEEN @start_date AND @end_date
  AND book = @book
  AND (@scope_all OR counterparty_id IN UNNEST(@counterparty_ids))
GROUP BY as_of_date
HAVING calls_raised > 0
ORDER BY call_amount DESC
LIMIT 20
