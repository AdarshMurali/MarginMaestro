"""Backfill of the simulated historical book (MM-140).

    python -m warehouse.backfill --list                 # the chunk names
    python -m warehouse.backfill --dims [--dry-run]     # dimensions + calendar
    python -m warehouse.backfill --chunk 2024-Q1 [--dry-run]
    python -m warehouse.backfill --all [--dry-run]      # dims + every chunk

Per trading day, for all 1,000 counterparties at once (numpy, see
warehouse.vector_calc -- proven equal to calc/ by the tests), the same math
the live app runs:

    VM        = MTM(close today) - MTM(prior close)       calc.vm
    IM        = sum |MTM| x risk weight x VIX multiplier   calc.im
    exposure  = VM + IM
    threshold = CSA threshold, or the reduced one once the rating is below
                the trigger grade                         calc.breach.effective_threshold
    breach    = max(0, exposure - threshold) - collateral > 0 and >= MTA
                                                          calc.breach.evaluate_breach

Calls, as the daily margin run would raise them (MM-125, ADR-0020): a
standing breach raises a call unless one is already open for that
counterparty; the intraday materiality gate doesn't apply (daily closes
only). Simplifications, all documented in docs/warehouse/README.md:
- A call is settled in cash the next trading day (the day after that when the
  client missed the SLA and it was escalated); collateral rises by the call.
- At each month-end, excess collateral is returned when the excess clears the
  MTA (the CSA Return Amount; the live app leaves returns out of scope).
- Positions are static over the five years; a position in a ticker listed
  later starts on its second priced day (VM needs a prior close).
- Lifecycle times (approval, notice, acknowledgement) are drawn from fixed
  distributions -- the simulated book has no humans. Every row says
  book = 'historical-sim'.

Chunks are calendar quarters. The path is simulated from the first day on
every run (collateral is path-dependent; it takes seconds), but only the
requested chunk's rows are written. Each chunk is written to gzip CSV files,
one per fact table (streamed day by day -- the 63M position rows are never
held in memory), then loaded with "drop the chunk's date partitions, append"
(warehouse.client). Re-running a chunk replaces it exactly; the result is
deterministic. --dry-run writes the files, prints rows and logical bytes per
table, and loads nothing.

No paths or table names come from the command line: the chunk is validated
against the fixed list, the output goes to the system temp directory.
"""

import argparse
import csv
import gzip
import os
import re
import sys
import tempfile
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, TextIO
from zoneinfo import ZoneInfo

import numpy as np
import structlog

from calc.materiality import exposure_sentence
from config.settings import get_settings
from persistence.models import CounterpartyTier
from streaming.schemas import MarketEventType
from warehouse import vector_calc as vc
from warehouse.client import WarehouseClient
from warehouse.dims import dim_date_rows, instrument_rows
from warehouse.history import VIX_SYMBOL, PriceMatrix, fetch_fred_rates, load_history
from warehouse.refresh import refresh_reports
from warehouse.schemas import (
    BOOK_KEY,
    DIM_COUNTERPARTY,
    DIM_CSA_TERMS,
    DIM_DATE,
    DIM_INSTRUMENT,
    FACT_DAILY_EXPOSURE,
    FACT_MARGIN_CALL,
    FACT_POSITION_DAILY,
    FACT_PRICE_DAILY,
    FIXED_SIZE,
    SIM_END_DATE,
    SIM_START_DATE,
    Book,
    Table,
    check_book_dates,
)
from warehouse.simulated_book import DEFAULT_SEED, SimulatedBook, generate_book
from warehouse.sp500 import Constituent, load_constituents

logger = structlog.get_logger()

BOOK = Book.HISTORICAL_SIM
CURRENCY = "USD"
# Prices are fetched from a little before the window so its first day has a
# prior close.
HISTORY_LEAD_DAYS = 14
MIN_COLLATERAL_USD = 10_000.0  # persistence.generators.collateral_calibration
RUN_TIME = (16, 45)  # the daily margin run, New York time
NEW_YORK = ZoneInfo("America/New_York")
SLA_MINUTES = 60
SLA_MET_CHANCE = {CounterpartyTier.STANDARD: 0.93, CounterpartyTier.ELITE: 0.97}
APPROVAL_MINUTES = (4.0, 40.0)
MANAGER_MINUTES = (5.0, 30.0)
ACK_MINUTES = (5.0, 55.0)
SIM_APPROVERS = tuple(f"sim-approver-{n}" for n in range(1, 6))
SIM_MANAGERS = ("sim-manager-1", "sim-manager-2")
CHUNK_PATTERN = re.compile(r"^(\d{4})-Q([1-4])$")


# --- chunks -------------------------------------------------------------------


@dataclass(frozen=True)
class Chunk:
    name: str
    start: date
    end: date


def all_chunks() -> list[Chunk]:
    chunks: list[Chunk] = []
    year, quarter = SIM_START_DATE.year, (SIM_START_DATE.month - 1) // 3 + 1
    while True:
        q_start = date(year, 3 * quarter - 2, 1)
        if q_start > SIM_END_DATE:
            return chunks
        q_end = (date(year + (quarter == 4), (3 * quarter) % 12 + 1, 1)) - timedelta(days=1)
        chunks.append(
            Chunk(f"{year}-Q{quarter}", max(q_start, SIM_START_DATE), min(q_end, SIM_END_DATE))
        )
        year, quarter = (year + 1, 1) if quarter == 4 else (year, quarter + 1)


def chunk_named(name: str) -> Chunk:
    if not CHUNK_PATTERN.match(name):
        raise ValueError(f"chunk must look like 2024-Q1, got {name!r}")
    for chunk in all_chunks():
        if chunk.name == name:
            return chunk
    raise ValueError(f"{name} is outside the simulated window {SIM_START_DATE}..{SIM_END_DATE}")


# --- the simulation -------------------------------------------------------------


@dataclass
class SimCall:
    counterparty_index: int
    as_of: date
    amount: float
    exposure: float
    collateral_held: float
    threshold: float
    sla_met: bool
    raised_at: datetime
    approved_at: datetime
    manager_approved_at: datetime | None
    approver: str
    notified_at: datetime
    resolved_at: datetime


@dataclass
class Day:
    """One trading day's results for every counterparty (arrays of length n)."""

    index: int
    as_of: date
    vix: float
    active: np.ndarray  # positions priced today and at the prior close
    close: np.ndarray  # today's close per position (NaN when not priced)
    variation_margin: np.ndarray
    initial_margin: np.ndarray
    exposure: np.ndarray
    threshold: np.ndarray
    mta: np.ndarray
    collateral: np.ndarray
    required: np.ndarray
    call_due: np.ndarray
    breached: np.ndarray
    call_raised: np.ndarray
    csa_version: np.ndarray
    rating: list[str]
    calls: list[SimCall] = field(default_factory=list)


class Simulation:
    """The simulated book on the price matrix, ready to walk day by day."""

    def __init__(self, book: SimulatedBook, prices: PriceMatrix, seed: int = DEFAULT_SEED) -> None:
        self.book = book
        self.prices = prices
        self.seed = seed
        self.n = len(book.counterparties)
        column = {t: j for j, t in enumerate(prices.tickers)}
        positions = book.positions
        self.pos_cp = np.array([p.counterparty_index for p in positions], dtype=np.int64)
        self.pos_col = np.array([column[p.ticker] for p in positions], dtype=np.int64)
        self.pos_qty = np.array([p.quantity for p in positions], dtype=np.float64)
        self.pos_weight = vc.risk_weights(
            [p.ticker for p in positions], [p.asset_class for p in positions]
        )
        self.tiers = [cp.tier for cp in book.counterparties]
        # Fast path for the 63M position rows: each position's constant CSV
        # middle and its constant logical bytes (4 x 8-byte values + strings).
        self.pos_prefix = [
            f"{BOOK.value},{book.counterparties[p.counterparty_index].id},"
            f"{p.position_id},{p.ticker},{p.asset_class.value}"
            for p in positions
        ]
        self.pos_bytes = np.array(
            [
                4 * FIXED_SIZE["FLOAT64"] + sum(_string_bytes(v) for v in prefix.split(","))
                for prefix in self.pos_prefix
            ],
            dtype=np.int64,
        )

    def _terms(self, day: date) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
        threshold = np.empty(self.n)
        mta = np.empty(self.n)
        version = np.empty(self.n, dtype=np.int64)
        rating_rank = np.empty(self.n, dtype=np.int64)
        trigger_rank = np.empty(self.n, dtype=np.int64)
        trigger_threshold = np.empty(self.n)
        ratings = []
        for i, cp in enumerate(self.book.counterparties):
            csa = cp.csa_on(day)
            rating = cp.rating_on(day)
            threshold[i], mta[i], version[i] = csa.threshold, csa.mta, csa.version
            trigger_rank[i] = vc.RATING_RANK[csa.trigger_below_grade]
            trigger_threshold[i] = csa.trigger_threshold
            rating_rank[i] = vc.RATING_RANK[rating]
            ratings.append(rating.value)
        effective = vc.effective_threshold(threshold, rating_rank, trigger_rank, trigger_threshold)
        return effective, mta, version, ratings

    def _lifecycle(self, rng: np.random.Generator, i: int, as_of: date) -> dict[str, Any]:
        raised = datetime(as_of.year, as_of.month, as_of.day, *RUN_TIME, tzinfo=NEW_YORK)
        raised = raised.astimezone(UTC)
        approved = raised + timedelta(minutes=float(rng.uniform(*APPROVAL_MINUTES)))
        manager = None
        if self.tiers[i] is CounterpartyTier.ELITE:
            manager = approved + timedelta(minutes=float(rng.uniform(*MANAGER_MINUTES)))
        notified = (manager or approved) + timedelta(minutes=1)
        sla_met = bool(rng.random() < SLA_MET_CHANCE[self.tiers[i]])
        resolved = notified + timedelta(
            minutes=float(rng.uniform(*ACK_MINUTES)) if sla_met else SLA_MINUTES
        )
        return {
            "raised_at": raised,
            "approved_at": approved,
            "manager_approved_at": manager,
            "approver": SIM_APPROVERS[int(rng.integers(len(SIM_APPROVERS)))],
            "notified_at": notified,
            "resolved_at": resolved,
            "sla_met": sla_met,
        }

    def days(self) -> Iterator[Day]:
        """Every trading day in [SIM_START_DATE, SIM_END_DATE], in order."""
        prices = self.prices
        collateral = np.zeros(self.n)
        pending = np.zeros(self.n)  # the open call's amount, delivered at settle_day
        settle_day = np.full(self.n, -1, dtype=np.int64)
        started = False
        for t in range(1, len(prices.dates)):
            as_of = prices.dates[t]
            if as_of < SIM_START_DATE or as_of > SIM_END_DATE:
                continue
            settling = settle_day == t
            collateral[settling] += pending[settling]
            pending[settling] = 0.0
            settle_day[settling] = -1

            today = prices.closes[t, self.pos_col]
            prior = prices.closes[t - 1, self.pos_col]
            active = ~np.isnan(today) & ~np.isnan(prior)
            cp, qty = self.pos_cp[active], self.pos_qty[active]
            mtm_today = vc.portfolio_mtm(cp, qty, today[active], self.n)
            mtm_prior = vc.portfolio_mtm(cp, qty, prior[active], self.n)
            vm = vc.variation_margin(mtm_today, mtm_prior)
            vix = float(prices.vix[t])
            im = vc.initial_margin(cp, qty, today[active], self.pos_weight[active], vix, self.n)
            exposure = vm + im
            threshold, mta, version, ratings = self._terms(as_of)

            if not started:  # opening collateral, sized on the first day's requirement
                opening = np.maximum(0.0, exposure - threshold)
                factors = np.array([c.collateral_factor for c in self.book.counterparties])
                collateral = np.maximum(MIN_COLLATERAL_USD, opening * factors)
                started = True

            breached, call_due, required = vc.evaluate_breach(exposure, collateral, threshold, mta)
            open_call = settle_day >= 0
            raised = breached & ~open_call
            held = collateral.copy()

            day = Day(
                index=t,
                as_of=as_of,
                vix=vix,
                active=active,
                close=today,
                variation_margin=vm,
                initial_margin=im,
                exposure=exposure,
                threshold=threshold,
                mta=mta,
                collateral=held,
                required=required,
                call_due=call_due,
                breached=breached,
                call_raised=raised,
                csa_version=version,
                rating=ratings,
            )
            rng = np.random.default_rng([self.seed, t, 7])
            for i in np.flatnonzero(raised):
                life = self._lifecycle(rng, int(i), as_of)
                day.calls.append(
                    SimCall(
                        counterparty_index=int(i),
                        as_of=as_of,
                        amount=float(call_due[i]),
                        exposure=float(exposure[i]),
                        collateral_held=float(held[i]),
                        threshold=float(threshold[i]),
                        **life,
                    )
                )
                pending[i] = call_due[i]
                settle_day[i] = t + (1 if life["sla_met"] else 2)

            if _is_month_end(prices.dates, t):
                returned = vc.return_amounts(collateral, required, mta)
                returned[settle_day >= 0] = 0.0  # never while a call is open
                collateral = collateral - returned
            yield day


def _is_month_end(dates: list[date], t: int) -> bool:
    return t + 1 >= len(dates) or dates[t + 1].month != dates[t].month


# --- rows ---------------------------------------------------------------------------


def _string_bytes(value: str | None) -> int:
    return 0 if value is None else 2 + len(value.encode("utf-8"))


def logical_bytes(table: Table, row: tuple) -> int:
    """BigQuery's logical (billed) size of one row: STRING = 2 + UTF-8
    length, INT64/FLOAT64/DATE/TIMESTAMP = 8, BOOL = 1, NULL = 0."""
    total = 0
    for column, value in zip(table.columns, row, strict=True):
        if value is None:
            continue
        if column.type == "STRING":
            total += _string_bytes(value)
        else:
            total += FIXED_SIZE[column.type]
    return total


def call_rationale(call: SimCall) -> str:
    return "Daily margin run (simulated). " + exposure_sentence(
        call.exposure, call.collateral_held, call.threshold, call.amount, CURRENCY, True
    )


def call_row(sim: Simulation, call: SimCall) -> tuple:
    cp = sim.book.counterparties[call.counterparty_index]
    return (
        call.as_of,
        BOOK.value,
        f"{cp.id}:{call.as_of.isoformat()}",
        cp.id,
        MarketEventType.DAILY_MARGIN_RUN.value,
        call.amount,
        CURRENCY,
        call_rationale(call),
        call.raised_at,
        "approved",
        call.approved_at,
        call.approver,
        call.manager_approved_at,
        call.notified_at,
        "simulated",
        call.resolved_at if call.sla_met else None,
        None if call.sla_met else call.resolved_at,
        "met" if call.sla_met else "breached",
        "sla_met" if call.sla_met else "escalated",
    )


def exposure_rows(sim: Simulation, day: Day) -> Iterator[tuple]:
    for i, cp in enumerate(sim.book.counterparties):
        yield (
            day.as_of,
            BOOK.value,
            cp.id,
            int(day.csa_version[i]),
            day.rating[i],
            day.vix,
            float(day.variation_margin[i]),
            float(day.initial_margin[i]),
            float(day.exposure[i]),
            float(day.threshold[i]),
            float(day.mta[i]),
            float(day.collateral[i]),
            float(day.required[i]),
            float(day.threshold[i] + day.collateral[i] - day.exposure[i]),
            float(day.call_due[i]),
            bool(day.breached[i]),
            bool(day.call_raised[i]),
            CURRENCY,
        )


def position_rows(sim: Simulation, day: Day) -> Iterator[tuple]:
    positions = sim.book.positions
    cps = sim.book.counterparties
    for k in np.flatnonzero(day.active):
        p = positions[k]
        close = float(day.close[k])
        yield (
            day.as_of,
            BOOK.value,
            cps[p.counterparty_index].id,
            p.position_id,
            p.ticker,
            p.asset_class.value,
            p.quantity,
            close,
            p.quantity * close,
        )


def price_rows(prices: PriceMatrix, t: int, rates: dict[str, dict[date, float]]) -> Iterator[tuple]:
    as_of = prices.dates[t]
    for j, ticker in enumerate(prices.tickers):
        value = prices.closes[t, j]
        if not np.isnan(value):
            yield (as_of, BOOK.value, ticker, "close", float(value), "yfinance")
    yield (as_of, BOOK.value, VIX_SYMBOL, "close", float(prices.vix[t]), "yfinance")
    for series_id in sorted(rates):
        if as_of in rates[series_id]:
            yield (as_of, BOOK.value, series_id, "rate", rates[series_id][as_of], "fred")


def counterparty_rows(book: SimulatedBook) -> Iterator[tuple]:
    for cp in book.counterparties:
        yield (
            BOOK_KEY[BOOK],
            BOOK.value,
            cp.id,
            cp.name,
            cp.type.value,
            cp.country,
            cp.tier.value,
            cp.rating_on(SIM_END_DATE).value,
        )


def csa_rows(book: SimulatedBook) -> Iterator[tuple]:
    for cp in book.counterparties:
        for v in cp.csa_versions:
            yield (
                BOOK_KEY[BOOK],
                BOOK.value,
                cp.id,
                v.version,
                v.valid_from,
                v.valid_to,
                v is cp.csa_versions[-1],
                v.threshold,
                v.mta,
                v.currency,
                v.trigger_below_grade.value,
                v.trigger_threshold,
                v.haircuts["cash"],
                v.haircuts["treasury"],
                v.haircuts["corporate"],
                v.haircuts["mmf"],
                v.change_reason,
            )


# --- chunk files ------------------------------------------------------------------

FACT_TABLES = (FACT_DAILY_EXPOSURE, FACT_POSITION_DAILY, FACT_MARGIN_CALL, FACT_PRICE_DAILY)


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, float):
        return repr(value)
    return str(value)


@dataclass
class TableStats:
    rows: int = 0
    logical_bytes: int = 0
    gzip_bytes: int = 0


class ChunkFiles:
    """One gzip CSV per fact table for one chunk, written as days stream in."""

    def __init__(self, chunk: Chunk, directory: Path) -> None:
        self.chunk = chunk
        self.paths = {t.name: directory / f"{chunk.name}-{t.name}.csv.gz" for t in FACT_TABLES}
        self._handles: dict[str, TextIO] = {}
        self._writers: dict[str, Any] = {}
        self.stats = {t.name: TableStats() for t in FACT_TABLES}
        for table in FACT_TABLES:
            handle = gzip.open(  # noqa: SIM115 -- closed in close()
                self.paths[table.name], "wt", encoding="utf-8", newline="", compresslevel=3
            )
            self._handles[table.name] = handle
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(table.column_names)
            self._writers[table.name] = writer

    def write_positions(self, sim: "Simulation", day: Day) -> None:
        """position_rows(), formatted without the csv module (no value in this
        table can contain a comma or quote) -- ~5x faster for 63M rows."""
        handle = self._handles[FACT_POSITION_DAILY.name]
        stats = self.stats[FACT_POSITION_DAILY.name]
        as_of = day.as_of.isoformat()
        quantity = sim.pos_qty
        lines = []
        for k in np.flatnonzero(day.active):
            close = float(day.close[k])
            q = float(quantity[k])
            lines.append(f"{as_of},{sim.pos_prefix[k]},{q!r},{close!r},{q * close!r}\n")
        handle.write("".join(lines))
        stats.rows += len(lines)
        stats.logical_bytes += int(sim.pos_bytes[day.active].sum())

    def write(self, table: Table, rows: Iterator[tuple]) -> None:
        writer = self._writers[table.name]
        stats = self.stats[table.name]
        for row in rows:
            writer.writerow([_fmt(v) for v in row])
            stats.rows += 1
            stats.logical_bytes += logical_bytes(table, row)

    def close(self) -> None:
        for name, handle in self._handles.items():
            handle.close()
            self.stats[name].gzip_bytes = self.paths[name].stat().st_size

    def remove(self) -> None:
        for path in self.paths.values():
            path.unlink(missing_ok=True)


# --- running ------------------------------------------------------------------------


@dataclass
class Inputs:
    book: SimulatedBook
    prices: PriceMatrix
    rates: dict[str, dict[date, float]]
    constituents: dict[str, Constituent]


def prepare_inputs(seed: int = DEFAULT_SEED) -> Inputs:
    constituents = {c.symbol: c for c in load_constituents()}
    lead = SIM_START_DATE - timedelta(days=HISTORY_LEAD_DAYS)
    prices = load_history(sorted(constituents), lead, SIM_END_DATE)
    first_close = {}
    for j, ticker in enumerate(prices.tickers):
        column = prices.closes[:, j]
        valid = np.flatnonzero(~np.isnan(column))
        if valid.size:
            first_close[ticker] = float(column[valid[0]])
    book = generate_book(prices.tickers, first_close, SIM_START_DATE, SIM_END_DATE, seed)
    return Inputs(book, prices, fetch_fred_rates(SIM_START_DATE, SIM_END_DATE), constituents)


def write_chunks(
    inputs: Inputs, chunks: list[Chunk], directory: Path, seed: int = DEFAULT_SEED
) -> Iterator[ChunkFiles]:
    """Walks the simulation once and yields each requested chunk's closed
    files as soon as its last day is written."""
    wanted = sorted(chunks, key=lambda c: c.start)
    for chunk in wanted:
        check_book_dates(BOOK, chunk.start, chunk.end)
    sim = Simulation(inputs.book, inputs.prices, seed)
    position = 0
    files: ChunkFiles | None = None
    for day in sim.days():
        while position < len(wanted) and day.as_of > wanted[position].end:
            if files is not None:
                files.close()
                yield files
                files = None
            position += 1
        if position >= len(wanted):
            break
        chunk = wanted[position]
        if day.as_of < chunk.start:
            continue
        if files is None:
            files = ChunkFiles(chunk, directory)
        files.write(FACT_DAILY_EXPOSURE, exposure_rows(sim, day))
        files.write_positions(sim, day)
        files.write(FACT_MARGIN_CALL, (call_row(sim, c) for c in day.calls))
        files.write(FACT_PRICE_DAILY, price_rows(inputs.prices, day.index, inputs.rates))
    if files is not None:
        files.close()
        yield files


def load_chunk(client: WarehouseClient, files: ChunkFiles) -> None:
    chunk = files.chunk
    for table in FACT_TABLES:
        client.replace_file(table, chunk.start, chunk.end, files.paths[table.name], "DATE")
    refresh_reports(client, chunk.start, chunk.end)


def load_dims(client: WarehouseClient | None, inputs: Inputs) -> dict[str, TableStats]:
    """The simulated book's dimensions (book_key 0) and the shared calendar."""
    key = BOOK_KEY[BOOK]
    held = sorted({p.ticker for p in inputs.book.positions})
    tables: list[tuple[Table, list[tuple]]] = [
        (DIM_COUNTERPARTY, list(counterparty_rows(inputs.book))),
        (DIM_INSTRUMENT, list(instrument_rows(BOOK, held, inputs.constituents))),
        (DIM_CSA_TERMS, list(csa_rows(inputs.book))),
        (DIM_DATE, list(dim_date_rows())),
    ]
    stats = {}
    for table, rows in tables:
        stats[table.name] = TableStats(
            rows=len(rows), logical_bytes=sum(logical_bytes(table, r) for r in rows)
        )
        if client is None:
            continue
        if table is DIM_DATE:
            client.overwrite_unpartitioned(table, rows)
        else:
            client.replace(table, key, key, rows, param_type="INT64")
    return stats


def _print_stats(label: str, stats: dict[str, TableStats], seconds: float | None = None) -> None:
    print(f"\n{label}")
    for name, s in stats.items():
        per_row = s.logical_bytes / s.rows if s.rows else 0
        print(
            f"  {name:<22} rows={s.rows:>12,}  logical={s.logical_bytes / 1e6:>10.1f} MB"
            f"  ({per_row:.0f} B/row)  gzip={s.gzip_bytes / 1e6:>8.1f} MB"
        )
    if seconds is not None:
        rows = sum(s.rows for s in stats.values())
        print(f"  {rows:,} rows in {seconds:.1f} s ({rows / max(seconds, 1e-9):,.0f} rows/s)")


def run(chunks: list[Chunk], dims: bool, dry_run: bool, seed: int = DEFAULT_SEED) -> None:
    started = time.perf_counter()
    inputs = prepare_inputs(seed)
    print(
        f"book: {len(inputs.book.counterparties):,} counterparties, "
        f"{len(inputs.book.positions):,} positions, {len(inputs.prices.tickers)} tickers, "
        f"{len(inputs.prices.dates)} price days, FRED series: {sorted(inputs.rates) or 'none'}"
        f" (prepared in {time.perf_counter() - started:.1f} s)"
    )
    client = None
    if not dry_run:
        project = get_settings().gcp_project_id
        if not project:
            raise SystemExit("GCP_PROJECT_ID is required (or use --dry-run)")
        client = WarehouseClient(project)
    if dims:
        _print_stats("dimensions", load_dims(client, inputs))
    directory = Path(tempfile.mkdtemp(prefix="mm-backfill-"))
    try:
        for files in _timed(write_chunks(inputs, chunks, directory, seed)):
            chunk_files, seconds = files
            if client is not None:
                load_chunk(client, chunk_files)
            _print_stats(
                f"chunk {chunk_files.chunk.name} ({chunk_files.chunk.start}..{chunk_files.chunk.end})"
                + (" [dry run, nothing loaded]" if client is None else " [loaded]"),
                chunk_files.stats,
                seconds,
            )
            chunk_files.remove()
    finally:
        for leftover in directory.glob("*"):
            leftover.unlink()
        os.rmdir(directory)
    print(f"\ndone in {time.perf_counter() - started:.1f} s")


def _timed(stream: Iterator[ChunkFiles]) -> Iterator[tuple[ChunkFiles, float]]:
    mark = time.perf_counter()
    for files in stream:
        now = time.perf_counter()
        yield files, now - mark
        mark = time.perf_counter()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m warehouse.backfill",
        description="Backfill the simulated historical book into BigQuery (MM-140)",
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--chunk", help="one quarter, e.g. 2024-Q1 (see --list)")
    target.add_argument("--all", action="store_true", help="dimensions + every chunk")
    target.add_argument("--dims", action="store_true", help="dimensions and the calendar only")
    target.add_argument("--list", action="store_true", help="print the chunk names")
    parser.add_argument("--dry-run", action="store_true", help="compute and size, load nothing")
    args = parser.parse_args(argv)

    if args.list:
        for chunk in all_chunks():
            print(f"{chunk.name}  {chunk.start}..{chunk.end}")
        return
    try:
        chunks = [chunk_named(args.chunk)] if args.chunk else []
    except ValueError as exc:
        parser.error(str(exc))
    if args.all:
        chunks = all_chunks()
    run(chunks, dims=args.all or args.dims, dry_run=args.dry_run)


if __name__ == "__main__":  # pragma: no cover
    main(sys.argv[1:])
