-- MM-142: refresh rpt_concentration (report 3) for whole months.
-- One snapshot per month: the last trading day loaded in that month (for the
-- live book's current month, the latest day -- replaced by each daily load).
-- @start_month / @end_month are first-of-month dates, so the DELETE drops
-- whole MONTH partitions (0 bytes).
-- Scans: fact_position_daily for those months' partitions, 6 columns
-- (~64 logical bytes/row: ~200 MB per quarter of the simulated book, ~4 GB
-- once for all five years; the live book's month is a few hundred KB);
-- dim_instrument (~50 KB).
DELETE FROM rpt_concentration
WHERE month_start BETWEEN @start_month AND @end_month;

INSERT INTO rpt_concentration (
  month_start, as_of_date, book, counterparty_id, ticker, sector, asset_class,
  gross_market_value, net_market_value
)
WITH snapshot AS (
  SELECT DATE_TRUNC(as_of_date, MONTH) AS month_start, MAX(as_of_date) AS as_of_date
  FROM fact_position_daily
  WHERE as_of_date BETWEEN @start_month AND LAST_DAY(@end_month)
  GROUP BY month_start
)
SELECT
  s.month_start,
  p.as_of_date,
  p.book,
  p.counterparty_id,
  p.ticker,
  COALESCE(i.sector, 'Unknown') AS sector,
  p.asset_class,
  ABS(p.market_value) AS gross_market_value,
  p.market_value AS net_market_value
FROM fact_position_daily AS p
JOIN snapshot AS s
  ON p.as_of_date = s.as_of_date
LEFT JOIN dim_instrument AS i
  ON i.book = p.book AND i.ticker = p.ticker
WHERE p.as_of_date BETWEEN @start_month AND LAST_DAY(@end_month);
