-- Report 5b, stress / backtest (MM-142): calls the threshold would have
-- triggered per month, against the month's VIX.
-- Reads rpt_counterparty_daily only, pruned to the range (same columns and
-- size as report_stress_days.sql).
SELECT
  DATE_TRUNC(as_of_date, MONTH) AS month,
  COUNTIF(call_raised) AS calls_raised,
  SUM(IF(call_raised, call_due, 0)) AS call_amount,
  COUNTIF(breached) AS breach_days,
  AVG(vix) AS avg_vix,
  MAX(vix) AS max_vix
FROM rpt_counterparty_daily
WHERE as_of_date BETWEEN @start_date AND @end_date
  AND book = @book
  AND (@scope_all OR counterparty_id IN UNNEST(@counterparty_ids))
GROUP BY month
ORDER BY month
