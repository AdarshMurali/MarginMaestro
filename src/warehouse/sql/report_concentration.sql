-- Report 3, concentration risk (MM-142): gross and net market value by
-- sector, asset class and the top tickers, for one month-end snapshot.
-- Reads rpt_concentration only, one MONTH partition: 7 columns, ~75 logical
-- bytes/row (~4 MB for a month of the simulated book).
WITH scoped AS (
  SELECT *
  FROM rpt_concentration
  WHERE month_start = @month
    AND book = @book
    AND (@scope_all OR counterparty_id IN UNNEST(@counterparty_ids))
)
SELECT 'sector' AS dimension, sector AS key, SUM(gross_market_value) AS gross,
  SUM(net_market_value) AS net, COUNT(DISTINCT counterparty_id) AS counterparties,
  MAX(as_of_date) AS as_of_date
FROM scoped
GROUP BY sector
UNION ALL
SELECT 'asset_class', asset_class, SUM(gross_market_value), SUM(net_market_value),
  COUNT(DISTINCT counterparty_id), MAX(as_of_date)
FROM scoped
GROUP BY asset_class
UNION ALL
(
  SELECT 'ticker', ticker, SUM(gross_market_value) AS gross, SUM(net_market_value),
    COUNT(DISTINCT counterparty_id), MAX(as_of_date)
  FROM scoped
  GROUP BY ticker
  ORDER BY gross DESC
  LIMIT 15
)
