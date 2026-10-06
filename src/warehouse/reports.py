"""The five warehouse reports behind the in-app /reports page (MM-142).

Each report runs one committed query (warehouse/sql/report_*.sql) against
the pre-aggregated report tables only -- never the facts -- with a bytes cap,
and the result is cached in-process for CACHE_SECONDS per (report, book,
period, scope), so page views don't re-scan.

Who sees what (the same scope as Cloud SQL row-level security, MM-106):
- Firm-wide roles (approver, manager, auditor): both books, every
  counterparty.
- Scoped users (margin analysts): the live book, only the counterparties in
  their user_counterparty_access rows. The simulated historical book is a
  firm-wide back-testing book with no analyst coverage, so it is firm-wide
  roles only; a scoped user asking for it gets ReportAccessError (403).
The numbers come from BigQuery, computed upstream by the calc engine; this
module only shapes them (groups the collateral buckets, picks the top rows).
"""

import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel

from persistence.db.rls import FIRM_WIDE
from warehouse.client import MB, QueryParam, WarehouseClient
from warehouse.refresh import sql
from warehouse.schemas import SIM_END_DATE, SIM_START_DATE, Book

CACHE_SECONDS = 600
REPORT_MAX_BYTES = 500 * MB
TOP_SHORTFALLS = 15
Period = Literal["3m", "1y", "5y"]
PERIOD_DAYS: dict[str, int] = {"3m": 92, "1y": 366, "5y": 1830}
COVERAGE_BUCKETS = ("under 80%", "80-100%", "100-120%", "120% or more", "no requirement")


class ReportAccessError(PermissionError):
    """The caller's scope doesn't cover the requested book."""


class ReportsUnavailableError(RuntimeError):
    """The warehouse isn't configured (WAREHOUSE=none)."""


def report_scope(scope: str, book: Book) -> tuple[bool, list[str]]:
    """(all counterparties?, the allowed counterparty ids) for a caller."""
    if scope == FIRM_WIDE:
        return True, []
    if book is Book.HISTORICAL_SIM:
        raise ReportAccessError("The simulated historical book is visible to firm-wide roles only.")
    return False, [cp for cp in scope.split(",") if cp]


def visible_books(scope: str) -> list[Book]:
    return [Book.LIVE, Book.HISTORICAL_SIM] if scope == FIRM_WIDE else [Book.LIVE]


def date_range(book: Book, period: str, today: date) -> tuple[date, date]:
    end = SIM_END_DATE if book is Book.HISTORICAL_SIM else today
    start = end - timedelta(days=PERIOD_DAYS[period])
    if book is Book.HISTORICAL_SIM:
        start = max(start, SIM_START_DATE)
    else:
        start = max(start, SIM_END_DATE + timedelta(days=1))
    return start, end


# --- response models -------------------------------------------------------------


class ReportMeta(BaseModel):
    book: str
    period: str
    start_date: date
    end_date: date
    generated_at: datetime
    scoped: bool


class ExposurePoint(BaseModel):
    as_of_date: date
    counterparties: int
    exposure: float
    threshold: float
    headroom: float
    breached: int
    shortfalls: int


class ExposureTrendReport(BaseModel):
    meta: ReportMeta
    points: list[ExposurePoint]


class CoverageBucket(BaseModel):
    bucket: str
    counterparties: int
    required_support: float
    collateral_held: float


class CounterpartyAdequacy(BaseModel):
    counterparty_id: str
    tier: str
    required_support: float
    collateral_held: float
    coverage_ratio: float | None
    headroom: float


class CollateralAdequacyReport(BaseModel):
    meta: ReportMeta
    as_of_date: date | None
    counterparties: int
    required_support: float
    collateral_held: float
    buckets: list[CoverageBucket]
    lowest_headroom: list[CounterpartyAdequacy]


class ConcentrationRow(BaseModel):
    key: str
    gross: float
    net: float
    counterparties: int


class ConcentrationReport(BaseModel):
    meta: ReportMeta
    as_of_date: date | None
    by_sector: list[ConcentrationRow]
    by_asset_class: list[ConcentrationRow]
    top_tickers: list[ConcentrationRow]


class MarginCallMonth(BaseModel):
    month: date
    calls: int
    amount: float
    avg_approval_minutes: float | None
    p90_approval_minutes: float | None
    sla_met: int
    sla_breached: int
    escalations: int
    open_calls: int


class MarginCallPerformanceReport(BaseModel):
    meta: ReportMeta
    months: list[MarginCallMonth]


class StressDay(BaseModel):
    as_of_date: date
    calls_raised: int
    call_amount: float
    breached: int
    vix: float


class StressMonth(BaseModel):
    month: date
    calls_raised: int
    call_amount: float
    breach_days: int
    avg_vix: float
    max_vix: float


class StressBacktestReport(BaseModel):
    meta: ReportMeta
    top_days: list[StressDay]
    months: list[StressMonth]


# --- the service -------------------------------------------------------------------


class ReportService:
    def __init__(
        self,
        client: WarehouseClient,
        ttl_seconds: float = CACHE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        today: Callable[[], date] = lambda: datetime.now(UTC).date(),
    ) -> None:
        self._client = client
        self._ttl = ttl_seconds
        self._clock = clock
        self._today = today
        self._cache: dict[tuple, tuple[float, BaseModel]] = {}

    def _cached(self, key: tuple, build: Callable[[], BaseModel]) -> Any:
        now = self._clock()
        hit = self._cache.get(key)
        if hit is not None and hit[0] > now:
            return hit[1]
        value = build()
        self._cache[key] = (now + self._ttl, value)
        return value

    def _context(self, scope: str, book: Book, period: str) -> tuple[ReportMeta, list[QueryParam]]:
        scope_all, ids = report_scope(scope, book)
        start, end = date_range(book, period, self._today())
        meta = ReportMeta(
            book=book.value,
            period=period,
            start_date=start,
            end_date=end,
            generated_at=datetime.now(UTC),
            scoped=not scope_all,
        )
        params = [
            QueryParam("book", "STRING", book.value),
            QueryParam("start_date", "DATE", start),
            QueryParam("end_date", "DATE", end),
            QueryParam("scope_all", "BOOL", scope_all),
            QueryParam("counterparty_ids", "STRING", ids, array=True),
        ]
        return meta, params

    def _rows(self, name: str, params: list[QueryParam]) -> list[dict[str, Any]]:
        return self._client.query(sql(name), params, max_bytes=REPORT_MAX_BYTES)

    def exposure_trend(self, scope: str, book: Book, period: str) -> ExposureTrendReport:
        def build() -> ExposureTrendReport:
            meta, params = self._context(scope, book, period)
            rows = self._rows("report_exposure_trend", params)
            return ExposureTrendReport(meta=meta, points=[ExposurePoint(**r) for r in rows])

        return self._cached(("exposure", scope, book, period), build)

    def collateral_adequacy(self, scope: str, book: Book, period: str) -> CollateralAdequacyReport:
        def build() -> CollateralAdequacyReport:
            meta, params = self._context(scope, book, period)
            rows = self._rows("report_collateral_adequacy", params)
            buckets = {
                name: CoverageBucket(
                    bucket=name, counterparties=0, required_support=0.0, collateral_held=0.0
                )
                for name in COVERAGE_BUCKETS
            }
            for row in rows:
                bucket = buckets[row["coverage_bucket"]]
                bucket.counterparties += 1
                bucket.required_support += row["required_support"]
                bucket.collateral_held += row["collateral_held"]
            return CollateralAdequacyReport(
                meta=meta,
                as_of_date=rows[0]["as_of_date"] if rows else None,
                counterparties=len(rows),
                required_support=sum(r["required_support"] for r in rows),
                collateral_held=sum(r["collateral_held"] for r in rows),
                buckets=list(buckets.values()),
                lowest_headroom=[
                    CounterpartyAdequacy(**{k: r[k] for k in CounterpartyAdequacy.model_fields})
                    for r in rows[:TOP_SHORTFALLS]
                ],
            )

        return self._cached(("collateral", scope, book, period), build)

    def concentration(self, scope: str, book: Book, period: str) -> ConcentrationReport:
        def build() -> ConcentrationReport:
            meta, params = self._context(scope, book, period)
            base = [p for p in params if p.name not in ("start_date", "end_date")]
            month = meta.end_date.replace(day=1)
            rows = self._rows("report_concentration", [*base, QueryParam("month", "DATE", month)])
            if not rows and book is Book.LIVE:
                # Early in a month before its first load: the previous month.
                previous = (month - timedelta(days=1)).replace(day=1)
                rows = self._rows(
                    "report_concentration", [*base, QueryParam("month", "DATE", previous)]
                )

            def pick(dimension: str) -> list[ConcentrationRow]:
                chosen = [r for r in rows if r["dimension"] == dimension]
                chosen.sort(key=lambda r: r["gross"], reverse=True)
                return [
                    ConcentrationRow(
                        key=r["key"],
                        gross=r["gross"],
                        net=r["net"],
                        counterparties=r["counterparties"],
                    )
                    for r in chosen
                ]

            return ConcentrationReport(
                meta=meta,
                as_of_date=max((r["as_of_date"] for r in rows), default=None),
                by_sector=pick("sector"),
                by_asset_class=pick("asset_class"),
                top_tickers=pick("ticker"),
            )

        return self._cached(("concentration", scope, book, period), build)

    def margin_call_performance(
        self, scope: str, book: Book, period: str
    ) -> MarginCallPerformanceReport:
        def build() -> MarginCallPerformanceReport:
            meta, params = self._context(scope, book, period)
            rows = self._rows("report_margin_call_performance", params)
            return MarginCallPerformanceReport(
                meta=meta, months=[MarginCallMonth(**r) for r in rows]
            )

        return self._cached(("margin_calls", scope, book, period), build)

    def stress_backtest(self, scope: str, book: Book, period: str) -> StressBacktestReport:
        def build() -> StressBacktestReport:
            meta, params = self._context(scope, book, period)
            return StressBacktestReport(
                meta=meta,
                top_days=[StressDay(**r) for r in self._rows("report_stress_days", params)],
                months=[StressMonth(**r) for r in self._rows("report_stress_monthly", params)],
            )

        return self._cached(("stress", scope, book, period), build)
