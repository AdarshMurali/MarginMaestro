"""The live book's daily warehouse load (MM-141).

After the daily margin run, the live counterparties' end-of-day state goes to
BigQuery with book = 'live':

- fact_daily_exposure -- recomputed here with the calc engine on the official
  closes in price_history (as_of and the prior close), VIXCLS from
  reference_rates, collateral and ratings from Cloud SQL, and the CSA terms
  the orchestrator itself last extracted for that counterparty (read from its
  checkpointed state -- no LLM call here, ever);
- fact_position_daily -- the positions snapshot at that day's close;
- fact_price_daily -- that day's closes and reference rates;
- fact_margin_call -- every call raised in the trailing CALL_WINDOW_DAYS,
  with its lifecycle so far (approval, notice, acknowledgement or
  escalation come from the audit trail), so a call approved or escalated
  after the day it was raised is updated by the next loads;
- dim_counterparty / dim_instrument / dim_csa_terms (book_key 1); the CSA
  terms become SCD2 versions whenever the extracted terms changed.

Idempotent per date: each table's slice is dropped (whole partitions) and
re-loaded, so a retry or a manual re-run for the same date replaces it. Live
owns only dates after SIM_END_DATE; earlier dates are refused.
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

import structlog
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from api.margin_calls import _effective_call_amount, _lifecycle_status
from calc.breach import effective_threshold, evaluate_breach
from calc.im import compute_initial_margin
from calc.models import CSATerms, PricingError
from calc.mtm import compute_mtm
from calc.vm import compute_variation_margin
from persistence.db.models import (
    AuditLogORM,
    CheckpointORM,
    CollateralItemORM,
    CounterpartyORM,
    PortfolioORM,
    PositionORM,
    PriceHistoryORM,
    RatingORM,
    ReferenceRateORM,
)
from persistence.models import AssetClass, Position, RatingGrade
from warehouse.client import WarehouseClient
from warehouse.dims import instrument_rows
from warehouse.refresh import refresh_reports
from warehouse.schemas import (
    BOOK_KEY,
    DIM_COUNTERPARTY,
    DIM_CSA_TERMS,
    DIM_INSTRUMENT,
    FACT_DAILY_EXPOSURE,
    FACT_MARGIN_CALL,
    FACT_POSITION_DAILY,
    FACT_PRICE_DAILY,
    SIM_END_DATE,
    Book,
    check_book_dates,
)
from warehouse.simulated_book import OPEN_END
from warehouse.sp500 import load_constituents

logger = structlog.get_logger()

BOOK = Book.LIVE
CALL_WINDOW_DAYS = 14
VIX_SERIES = "VIXCLS"


class NoClosesError(RuntimeError):
    """No official closes are loaded for the requested date (a holiday, or
    the EOD load hasn't run)."""


# --- inputs ------------------------------------------------------------------------


@dataclass
class LiveCounterparty:
    id: str
    name: str
    type: str
    country: str
    tier: str
    rating: RatingGrade | None
    positions: list[Position]
    collateral_held: float


@dataclass
class Snapshot:
    as_of: date
    counterparties: list[LiveCounterparty]
    closes: dict[str, float]
    prior_closes: dict[str, float]
    vix: float | None
    rates: dict[str, float]


@dataclass
class RunRecord:
    thread_id: str
    values: dict[str, Any]
    events: list[tuple[str, datetime, dict]] = field(default_factory=list)


def latest_close_date(session: Session) -> date | None:
    return session.execute(select(func.max(PriceHistoryORM.price_date))).scalar_one_or_none()


def read_snapshot(session: Session, as_of: date) -> Snapshot:
    closes = {
        ticker: price
        for ticker, price in session.execute(
            select(PriceHistoryORM.ticker, PriceHistoryORM.price).where(
                PriceHistoryORM.price_date == as_of
            )
        ).all()
    }
    if not closes:
        raise NoClosesError(f"no closes in price_history for {as_of}")
    prior_date = (
        select(PriceHistoryORM.ticker, func.max(PriceHistoryORM.price_date).label("d"))
        .where(PriceHistoryORM.price_date < as_of)
        .group_by(PriceHistoryORM.ticker)
        .subquery()
    )
    prior = {
        ticker: price
        for ticker, price in session.execute(
            select(PriceHistoryORM.ticker, PriceHistoryORM.price).join(
                prior_date,
                (PriceHistoryORM.ticker == prior_date.c.ticker)
                & (PriceHistoryORM.price_date == prior_date.c.d),
            )
        ).all()
    }
    vix = session.execute(
        select(ReferenceRateORM.value)
        .where(ReferenceRateORM.series_id == VIX_SERIES, ReferenceRateORM.rate_date <= as_of)
        .order_by(ReferenceRateORM.rate_date.desc())
        .limit(1)
    ).scalar_one_or_none()
    rates = {
        series: value
        for series, value in session.execute(
            select(ReferenceRateORM.series_id, ReferenceRateORM.value).where(
                ReferenceRateORM.rate_date == as_of
            )
        ).all()
    }

    positions: dict[str, list[Position]] = defaultdict(list)
    for row, counterparty_id in session.execute(
        select(PositionORM, PortfolioORM.counterparty_id).join(
            PortfolioORM, PositionORM.portfolio_id == PortfolioORM.id
        )
    ).all():
        positions[counterparty_id].append(
            Position(
                id=row.id,
                portfolio_id=row.portfolio_id,
                ticker=row.ticker,
                asset_class=AssetClass(row.asset_class),
                quantity=row.quantity,
                trade_date=row.trade_date,
            )
        )
    collateral: dict[str, float] = defaultdict(float)
    for counterparty_id, value, haircut in session.execute(
        select(
            CollateralItemORM.counterparty_id,
            CollateralItemORM.value_usd,
            CollateralItemORM.haircut_pct,
        )
    ).all():
        collateral[counterparty_id] += value * (1 - haircut)  # persistence.queries.collateral_held
    ratings: dict[str, RatingGrade] = {}
    for counterparty_id, grade in session.execute(
        select(RatingORM.counterparty_id, RatingORM.grade).order_by(RatingORM.rating_date.asc())
    ).all():
        ratings[counterparty_id] = RatingGrade(grade)  # the latest wins

    counterparties = [
        LiveCounterparty(
            id=row.id,
            name=row.name,
            type=row.type,
            country=row.country,
            tier=row.tier,
            rating=ratings.get(row.id),
            positions=positions.get(row.id, []),
            collateral_held=collateral.get(row.id, 0.0),
        )
        for row in session.execute(select(CounterpartyORM).order_by(CounterpartyORM.id))
        .scalars()
        .all()
    ]
    return Snapshot(as_of, counterparties, closes, prior, vix, rates)


def read_runs(graph: CompiledStateGraph, session: Session) -> list[RunRecord]:
    """Every orchestrator run with its audit events (the same discovery the
    margin-call feed uses: thread ids from the checkpoint table)."""
    thread_ids = session.execute(select(CheckpointORM.thread_id).distinct()).scalars().all()
    runs = []
    for thread_id in thread_ids:
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
        values = graph.get_state(config).values
        if values:
            runs.append(RunRecord(thread_id, dict(values)))
    keys = {(r.values["correlation_id"], r.values["counterparty_id"]) for r in runs}
    if keys:
        correlation_ids = sorted({k[0] for k in keys})
        events: dict[tuple[str, str], list] = defaultdict(list)
        for row in (
            session.execute(
                select(AuditLogORM)
                .where(AuditLogORM.correlation_id.in_(correlation_ids))
                .order_by(AuditLogORM.created_at.asc(), AuditLogORM.id.asc())
            )
            .scalars()
            .all()
        ):
            events[(row.correlation_id, row.counterparty_id or "")].append(
                (row.event_type, _utc(row.created_at), row.payload or {})
            )
        for run in runs:
            run.events = events.get(
                (run.values["correlation_id"], run.values["counterparty_id"]), []
            )
    return runs


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


# --- rows ------------------------------------------------------------------------------


def _run_time(run: RunRecord) -> datetime:
    return _utc(run.values["impact"].occurred_at)


def csa_versions(runs: list[RunRecord]) -> dict[str, list[tuple[date, CSATerms]]]:
    """Per counterparty, each distinct set of extracted CSA terms with the
    first date it was used: the SCD2 history of what the orchestrator read."""
    versions: dict[str, list[tuple[date, CSATerms]]] = defaultdict(list)
    for run in sorted(runs, key=_run_time):
        terms = run.values.get("csa_terms")
        if terms is None:
            continue
        history = versions[run.values["counterparty_id"]]
        if not history or history[-1][1] != terms:
            history.append((_run_time(run).date(), terms))
    return versions


def terms_on(history: list[tuple[date, CSATerms]], as_of: date) -> tuple[int, CSATerms] | None:
    """The version in force on as_of (or the first one, for a date before
    any run used CSA terms)."""
    chosen = None
    for number, (valid_from, terms) in enumerate(history, start=1):
        if valid_from <= as_of or chosen is None:
            chosen = (number, terms)
    return chosen


def exposure_and_positions(
    snapshot: Snapshot, versions: dict[str, list[tuple[date, CSATerms]]]
) -> tuple[list[tuple], list[tuple], list[str]]:
    """fact_daily_exposure and fact_position_daily rows, with the calc engine
    exactly as the daily run uses it; plus why any counterparty was skipped."""
    exposure_rows, position_rows, skipped = [], [], []
    for cp in snapshot.counterparties:
        version = terms_on(versions.get(cp.id, []), snapshot.as_of)
        reason = _skip_reason(cp, snapshot, version)
        if reason:
            skipped.append(f"{cp.id}: {reason}")
            continue
        assert version is not None and snapshot.vix is not None
        number, terms = version
        try:
            today = compute_mtm(cp.positions, snapshot.closes)
            prior = compute_mtm(cp.positions, snapshot.prior_closes)
            vm = compute_variation_margin(today, prior).variation_margin
            im = compute_initial_margin(today, snapshot.vix).initial_margin
        except PricingError as exc:
            skipped.append(f"{cp.id}: {exc}")
            continue
        exposure = vm + im
        threshold = effective_threshold(terms, cp.rating)
        breach = evaluate_breach(exposure, cp.collateral_held, terms, cp.rating)
        exposure_rows.append(
            (
                snapshot.as_of,
                BOOK.value,
                cp.id,
                number,
                cp.rating.value if cp.rating else None,
                snapshot.vix,
                vm,
                im,
                exposure,
                threshold,
                terms.mta,
                cp.collateral_held,
                max(0.0, exposure - threshold),
                threshold + cp.collateral_held - exposure,
                breach.call_amount,
                breach.breached,
                False,
                terms.currency,
            )
        )
        for pm in today.positions:
            position_rows.append(
                (
                    snapshot.as_of,
                    BOOK.value,
                    cp.id,
                    pm.position_id,
                    pm.ticker,
                    pm.asset_class.value,
                    pm.quantity,
                    pm.price,
                    pm.mtm,
                )
            )
    return exposure_rows, position_rows, skipped


def _skip_reason(
    cp: LiveCounterparty, snapshot: Snapshot, version: tuple[int, CSATerms] | None
) -> str | None:
    if not cp.positions:
        return "no positions"
    if version is None:
        return "no CSA terms extracted by any run yet"
    if snapshot.vix is None:
        return f"no {VIX_SERIES} on or before {snapshot.as_of}"
    tickers = {p.ticker for p in cp.positions}
    missing = sorted(
        t for t in tickers if t not in snapshot.closes or t not in snapshot.prior_closes
    )
    if missing:
        return f"no close for {', '.join(missing)}"
    return None


def _first(
    events: Iterable[tuple[str, datetime, dict]], event_type: str, **match: Any
) -> tuple | None:
    for kind, at, payload in events:
        if kind != event_type:
            continue
        if all(
            (payload.get(k) is not None) if v is ... else payload.get(k) == v
            for k, v in match.items()
        ):
            return at, payload
    return None


def margin_call_row(run: RunRecord) -> tuple | None:
    """One fact_margin_call row, or None when the run raised no call (no
    breach, or held by the materiality gate)."""
    values = run.values
    breach = values.get("breach_result")
    if breach is None or not breach.breached or values.get("materiality") == "below_mta":
        return None
    raised = _first(run.events, "evaluate_breach")
    raised_at = raised[0] if raised else _run_time(run)
    approval = _first(run.events, "await_approval", decision=...)
    manager = _first(run.events, "await_manager_approval", manager_decision=...)
    acknowledged = _first(run.events, "await_sla_response", sla_outcome="met")
    escalated = _first(run.events, "escalate")
    notification = values.get("notification_result")
    terms = values.get("csa_terms")
    return (
        raised_at.date(),
        BOOK.value,
        run.thread_id,
        values["counterparty_id"],
        values["impact"].event_type.value,
        _effective_call_amount(values, breach),
        terms.currency if terms is not None else "USD",
        values.get("call_rationale"),
        raised_at,
        values.get("approval_decision"),
        approval[0] if approval else None,
        approval[1].get("approver_username") if approval else None,
        manager[0] if manager else None,
        _utc(values["notification_sent_at"]) if values.get("notification_sent_at") else None,
        notification.channel if notification is not None else None,
        acknowledged[0] if acknowledged else None,
        escalated[0] if escalated else None,
        values.get("sla_outcome"),
        _lifecycle_status(values).value,
    )


def price_rows(snapshot: Snapshot) -> list[tuple]:
    rows = [
        (snapshot.as_of, BOOK.value, ticker, "close", price, "eod")
        for ticker, price in sorted(snapshot.closes.items())
    ]
    rows += [
        (snapshot.as_of, BOOK.value, series, "rate", value, "fred")
        for series, value in sorted(snapshot.rates.items())
    ]
    return rows


def dimension_rows(
    snapshot: Snapshot, versions: dict[str, list[tuple[date, CSATerms]]]
) -> dict[str, list[tuple]]:
    key = BOOK_KEY[BOOK]
    counterparties = [
        (
            key,
            BOOK.value,
            cp.id,
            cp.name,
            cp.type,
            cp.country,
            cp.tier,
            cp.rating.value if cp.rating else None,
        )
        for cp in snapshot.counterparties
    ]
    tickers = sorted({p.ticker for cp in snapshot.counterparties for p in cp.positions})
    constituents = {c.symbol: c for c in load_constituents()}
    csa = []
    for counterparty_id, history in sorted(versions.items()):
        for number, (valid_from, terms) in enumerate(history, start=1):
            is_current = number == len(history)
            valid_to = OPEN_END if is_current else history[number][0] - timedelta(days=1)
            trigger = min(terms.rating_triggers, key=lambda t: t.reduced_threshold, default=None)
            csa.append(
                (
                    key,
                    BOOK.value,
                    counterparty_id,
                    number,
                    valid_from,
                    valid_to,
                    is_current,
                    terms.threshold,
                    terms.mta,
                    terms.currency,
                    trigger.below_grade.value if trigger else None,
                    trigger.reduced_threshold if trigger else None,
                    None,
                    None,
                    None,
                    None,
                    "extracted",
                )
            )
    return {
        DIM_COUNTERPARTY.name: counterparties,
        DIM_INSTRUMENT.name: list(instrument_rows(BOOK, tickers, constituents)),
        DIM_CSA_TERMS.name: csa,
    }


# --- the load ----------------------------------------------------------------------------


@dataclass
class LoadResult:
    as_of: date
    rows: dict[str, int]
    skipped: list[str]


def load_live_day(
    client: WarehouseClient,
    session_factory: sessionmaker[Session],
    graph: CompiledStateGraph,
    as_of: date | None = None,
) -> LoadResult:
    """Loads one day (default: the latest date with official closes)."""
    with session_factory() as session:
        as_of = as_of or latest_close_date(session)
        if as_of is None:
            raise NoClosesError("price_history is empty")
        check_book_dates(BOOK, as_of, as_of)
        snapshot = read_snapshot(session, as_of)
        runs = read_runs(graph, session)

    versions = csa_versions(runs)
    exposure, positions, skipped = exposure_and_positions(snapshot, versions)
    window_start = max(
        as_of - timedelta(days=CALL_WINDOW_DAYS - 1), SIM_END_DATE + timedelta(days=1)
    )
    calls = [
        row
        for row in (margin_call_row(run) for run in runs)
        if row is not None and window_start <= row[0] <= as_of
    ]

    rows = {
        FACT_DAILY_EXPOSURE.name: client.replace(FACT_DAILY_EXPOSURE, as_of, as_of, exposure),
        FACT_POSITION_DAILY.name: client.replace(FACT_POSITION_DAILY, as_of, as_of, positions),
        FACT_PRICE_DAILY.name: client.replace(FACT_PRICE_DAILY, as_of, as_of, price_rows(snapshot)),
        FACT_MARGIN_CALL.name: client.replace(FACT_MARGIN_CALL, window_start, as_of, calls),
    }
    key = BOOK_KEY[BOOK]
    dims = dimension_rows(snapshot, versions)
    for table in (DIM_COUNTERPARTY, DIM_INSTRUMENT, DIM_CSA_TERMS):
        rows[table.name] = client.replace(table, key, key, dims[table.name], param_type="INT64")
    refresh_reports(client, window_start, as_of)
    for reason in skipped:
        logger.warning("warehouse_live_counterparty_skipped", as_of=str(as_of), reason=reason)
    logger.info("warehouse_live_load", as_of=str(as_of), rows=rows, skipped=len(skipped))
    return LoadResult(as_of=as_of, rows=rows, skipped=skipped)
