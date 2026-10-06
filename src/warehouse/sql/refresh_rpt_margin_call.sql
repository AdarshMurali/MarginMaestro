-- MM-142: refresh rpt_margin_call (report 4) for whole months (MONTH
-- partitions, so the DELETE is a 0-byte partition drop).
-- Scans: fact_margin_call for those months, 11 columns (~110 logical
-- bytes/call; the rationale text is not read), and dim_counterparty (~40 KB).
DELETE FROM rpt_margin_call
WHERE raised_date BETWEEN @start_month AND LAST_DAY(@end_month);

INSERT INTO rpt_margin_call (
  raised_date, book, call_id, counterparty_id, tier, trigger_type, call_amount,
  approval_minutes, notify_minutes, sla_outcome, escalated, status
)
SELECT
  m.raised_date,
  m.book,
  m.call_id,
  m.counterparty_id,
  c.tier,
  m.trigger_type,
  m.call_amount,
  TIMESTAMP_DIFF(m.approved_at, m.raised_at, SECOND) / 60.0 AS approval_minutes,
  TIMESTAMP_DIFF(m.notified_at, m.raised_at, SECOND) / 60.0 AS notify_minutes,
  m.sla_outcome,
  m.escalated_at IS NOT NULL AS escalated,
  m.status
FROM fact_margin_call AS m
LEFT JOIN dim_counterparty AS c
  ON c.book = m.book AND c.counterparty_id = m.counterparty_id
WHERE m.raised_date BETWEEN @start_month AND LAST_DAY(@end_month);
