-- Report 4, margin-call performance (MM-142): per month, volume, amounts,
-- approval turnaround, SLA met/breached and escalations.
-- Reads rpt_margin_call only, pruned to the range: 9 columns, ~75 logical
-- bytes/call (~10 MB for all ~127k simulated calls).
SELECT
  DATE_TRUNC(raised_date, MONTH) AS month,
  COUNT(*) AS calls,
  SUM(call_amount) AS amount,
  AVG(approval_minutes) AS avg_approval_minutes,
  APPROX_QUANTILES(approval_minutes, 100)[OFFSET(90)] AS p90_approval_minutes,
  COUNTIF(sla_outcome = 'met') AS sla_met,
  COUNTIF(sla_outcome = 'breached') AS sla_breached,
  COUNTIF(escalated) AS escalations,
  COUNTIF(sla_outcome IS NULL) AS open_calls
FROM rpt_margin_call
WHERE raised_date BETWEEN @start_date AND @end_date
  AND book = @book
  AND (@scope_all OR counterparty_id IN UNNEST(@counterparty_ids))
GROUP BY month
ORDER BY month
