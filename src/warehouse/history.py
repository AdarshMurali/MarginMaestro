"""Five years of real daily closes for the simulated book (MM-140).

Downloads Yahoo Finance daily closes (split-adjusted, not dividend-adjusted:
`auto_adjust=False`'s Close) for every ticker, in batches with retries, and
caches them as one gzip CSV under `data/warehouse_cache/` (git-ignored, fixed
name per window). A re-run reads the cache; delete the file to re-download.
Also fetches ^VIX (the CBOE VIX close -- the same series FRED publishes as
VIXCLS, which the live app's initial margin reads) and, when FRED_API_KEY is
set, the FRED reference rates; without a key those are skipped.

Gzip CSV instead of parquet: parquet needs pyarrow (~100 MB installed) in the
app image for a cache that is read once per backfill.

Gaps: a ticker's days before its first close (listed later) stay missing --
positions in it start on its first priced day. A gap after that (a halted
day) is forward-filled from the last close, at most MAX_FILL_DAYS days.
"""

import csv
import gzip
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import structlog
from numpy.typing import NDArray

from config.settings import Settings, get_settings

logger = structlog.get_logger()

CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "warehouse_cache"
VIX_SYMBOL = "^VIX"
BATCH_SIZE = 100
MAX_ATTEMPTS = 4
MAX_FILL_DAYS = 5
# A date is a trading day if at least this share of tickers closed on it.
MIN_COVERAGE = 0.5
FRED_SERIES = ("SOFR", "DGS2", "DGS10", "DGS30", "VIXCLS")


class HistoryError(RuntimeError):
    """Prices could not be fetched or are unusable."""


@dataclass
class PriceMatrix:
    dates: list[date]
    tickers: list[str]
    closes: NDArray[np.float64]  # (days, tickers); NaN = no close
    vix: NDArray[np.float64]  # (days,)

    def column(self, ticker: str) -> NDArray[np.float64]:
        return self.closes[:, self.tickers.index(ticker)]

    def slice_dates(self, start: date, end: date) -> "PriceMatrix":
        keep = [i for i, d in enumerate(self.dates) if start <= d <= end]
        return PriceMatrix(
            dates=[self.dates[i] for i in keep],
            tickers=list(self.tickers),
            closes=self.closes[keep],
            vix=self.vix[keep],
        )


Downloader = Callable[[list[str], date, date], dict[str, dict[date, float]]]


def _yfinance_download(tickers: list[str], start: date, end: date) -> dict[str, dict[date, float]]:
    import yfinance as yf

    frame = yf.download(
        tickers,
        start=start.isoformat(),
        end=(end + timedelta(days=1)).isoformat(),
        auto_adjust=False,
        progress=False,
        threads=True,
        group_by="column",
    )
    if frame is None or frame.empty:
        return {}
    closes = frame["Close"]
    result: dict[str, dict[date, float]] = {}
    for ticker in tickers:
        if ticker not in closes:
            continue
        series = closes[ticker].dropna()
        result[ticker] = {ts.date(): float(v) for ts, v in series.items()}
    return result


def download_closes(
    tickers: list[str],
    start: date,
    end: date,
    downloader: Downloader = _yfinance_download,
    sleep: Callable[[float], None] | None = None,
) -> dict[str, dict[date, float]]:
    """Batches of BATCH_SIZE, each retried with backoff; tickers still empty
    after the last attempt are reported and left out."""
    result: dict[str, dict[date, float]] = {}
    for offset in range(0, len(tickers), BATCH_SIZE):
        batch = tickers[offset : offset + BATCH_SIZE]
        pending = list(batch)
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                fetched = downloader(pending, start, end)
            except Exception as exc:  # noqa: BLE001 -- network / rate limit: retry the batch
                logger.warning("history_batch_failed", attempt=attempt, error=str(exc))
                fetched = {}
            for ticker, closes in fetched.items():
                if closes:
                    result[ticker] = closes
            pending = [t for t in pending if t not in result]
            if not pending:
                break
            if attempt < MAX_ATTEMPTS:
                (sleep or time.sleep)(2.0**attempt)
        if pending:
            logger.warning("history_tickers_missing", tickers=pending)
    return result


def build_matrix(
    closes: dict[str, dict[date, float]], tickers: list[str], vix: dict[date, float]
) -> PriceMatrix:
    """Aligns everything on the trading calendar (dates where most tickers
    closed and VIX printed) and forward-fills short gaps."""
    present = [t for t in tickers if closes.get(t)]
    if not present:
        raise HistoryError("no closes for any ticker")
    counts: dict[date, int] = {}
    for t in present:
        for d in closes[t]:
            counts[d] = counts.get(d, 0) + 1
    dates = sorted(d for d, n in counts.items() if n >= MIN_COVERAGE * len(present) and d in vix)
    if not dates:
        raise HistoryError("no trading days with enough closes and a VIX close")
    matrix = np.full((len(dates), len(present)), np.nan)
    for j, t in enumerate(present):
        series = closes[t]
        matrix[:, j] = [series.get(d, np.nan) for d in dates]
    _forward_fill(matrix)
    return PriceMatrix(
        dates=dates,
        tickers=present,
        closes=matrix,
        vix=np.array([vix[d] for d in dates], dtype=np.float64),
    )


def _forward_fill(matrix: NDArray[np.float64]) -> None:
    days, cols = matrix.shape
    for j in range(cols):
        column = matrix[:, j]
        valid = np.flatnonzero(~np.isnan(column))
        if valid.size == 0:
            continue
        gap = 0
        for i in range(valid[0] + 1, days):
            if np.isnan(column[i]):
                gap += 1
                if gap <= MAX_FILL_DAYS:
                    column[i] = column[i - 1]
            else:
                gap = 0


def cache_path(start: date, end: date) -> Path:
    return CACHE_DIR / f"closes_{start:%Y%m%d}_{end:%Y%m%d}.csv.gz"


def save_cache(path: Path, closes: dict[str, dict[date, float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["symbol", "date", "close"])
        for symbol in sorted(closes):
            for d in sorted(closes[symbol]):
                writer.writerow([symbol, d.isoformat(), repr(closes[symbol][d])])


def load_cache(path: Path) -> dict[str, dict[date, float]]:
    closes: dict[str, dict[date, float]] = {}
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            closes.setdefault(row["symbol"], {})[date.fromisoformat(row["date"])] = float(
                row["close"]
            )
    return closes


def load_history(
    tickers: list[str],
    start: date,
    end: date,
    downloader: Downloader = _yfinance_download,
    cache: Path | None = None,
) -> PriceMatrix:
    """Cached closes for `tickers` + VIX over [start, end]."""
    path = cache or cache_path(start, end)
    if path.is_file():
        closes = load_cache(path)
        logger.info("history_cache_hit", symbols=len(closes))
    else:
        closes = download_closes([*tickers, VIX_SYMBOL], start, end, downloader)
        save_cache(path, closes)
        logger.info("history_downloaded", symbols=len(closes))
    vix = closes.get(VIX_SYMBOL)
    if not vix:
        raise HistoryError("no VIX closes; initial margin can't be computed")
    return build_matrix(closes, tickers, vix)


def fetch_fred_rates(
    start: date, end: date, settings: Settings | None = None
) -> dict[str, dict[date, float]]:
    """FRED reference rates over the window, or {} without FRED_API_KEY."""
    from persistence.fred_feed import FredFeed, RateDataUnavailableError

    try:
        feed = FredFeed(settings or get_settings())
    except RateDataUnavailableError:
        logger.info("fred_rates_skipped", reason="FRED_API_KEY is not configured")
        return {}
    rates: dict[str, dict[date, float]] = {}
    for series_id in FRED_SERIES:
        try:
            observations = feed.get_series(series_id, start=start, end=end)
        except RateDataUnavailableError as exc:
            logger.warning("fred_series_unavailable", series_id=series_id, error=str(exc))
            continue
        rates[series_id] = {o.date: o.value for o in observations}
    return rates
