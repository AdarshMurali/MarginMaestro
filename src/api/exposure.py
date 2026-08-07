"""Positions & exposure board (MM-52): per-counterparty positions, prices,
and a deterministic status light (healthy/at_risk/breached/unavailable),
built from the same calc modules the orchestrator uses for a single
margin-call run -- code computes the numbers, never the LLM (golden rule 1).
Prices (current and historical) are read from SQL only (MM-59) -- never a
request-time yfinance call; see streaming/live_feed_poller.py and
streaming/event_agent.py's upsert_latest_price for how latest_prices/
price_history get populated."""

from datetime import UTC, datetime
from functools import lru_cache

import structlog
from sqlalchemy.orm import Session

from agents.csa_rag import CSATermsUnavailableError, answer_csa_terms
from api.schemas import (
    CounterpartyExposure,
    CounterpartyListResponse,
    CounterpartySummary,
    ExposureBoardResponse,
    ExposureStatus,
    PositionExposure,
    PriceHistoryResponse,
    PricePoint,
)
from calc.breach import evaluate_breach
from calc.im import compute_initial_margin
from calc.models import BreachResult, CSATerms, PricingError
from calc.mtm import compute_mtm
from calc.vm import compute_variation_margin
from persistence.models import Counterparty, Position
from persistence.queries import (
    collateral_held,
    collateral_held_for_counterparties,
    get_counterparty,
    latest_closes_before,
    latest_prices,
    latest_vix,
    list_counterparties,
    load_positions,
    load_positions_for_counterparties,
)
from persistence.queries import price_history as price_history_rows
from rag.models import CSATermsResult
from streaming.market_feed import MarketDataUnavailableError

logger = structlog.get_logger()

# A counterparty whose exposure has already reached this fraction of its CSA
# threshold is flagged "at risk" even before it actually breaches -- gives
# the dashboard's amber light somewhere to mean something other than "about
# to turn red at the last possible second".
AT_RISK_THRESHOLD_FRACTION = 0.8


@lru_cache(maxsize=64)
def _cached_csa_terms(counterparty_id: str) -> CSATermsResult | str:
    """CSA terms are extracted (RAG + LLM) from static demo policy documents
    that don't change during a session -- cached per process so repeated
    exposure-board requests don't re-run extraction for the same
    counterparty on every poll. Distinct from the orchestrator's
    fetch_csa_terms, a one-shot call per margin-call run that deliberately
    stays uncached (correctness there matters more than call volume).

    A failure (no CSA documents for this counterparty) is just as static as
    a success for this demo corpus, so it's cached too (MM-66) -- returned
    as a plain str rather than raised, since lru_cache doesn't memoize
    exceptions. Without this, a counterparty with no CSA docs (e.g. a
    leftover simulate-event test counterparty like CP-E2E/CP-MM55) re-runs
    the real RAG lookup on every single board request, forever -- this was
    the dominant cost behind /exposure's ~2-4s latency, well past the SQL
    N+1 fix in this same story."""
    try:
        return answer_csa_terms(counterparty_id)
    except CSATermsUnavailableError as exc:
        return str(exc)


def _csa_terms(counterparty_id: str) -> CSATermsResult:
    result = _cached_csa_terms(counterparty_id)
    if isinstance(result, str):
        raise CSATermsUnavailableError(result)
    return result


def _classify_status(
    exposure: float, csa_terms: CSATerms, breach_result: BreachResult
) -> ExposureStatus:
    if breach_result.breached:
        return ExposureStatus.BREACHED
    if csa_terms.threshold > 0 and exposure >= AT_RISK_THRESHOLD_FRACTION * csa_terms.threshold:
        return ExposureStatus.AT_RISK
    return ExposureStatus.HEALTHY


def _unavailable(
    counterparty: Counterparty, detail: str, positions: list[PositionExposure]
) -> CounterpartyExposure:
    return CounterpartyExposure(
        counterparty_id=counterparty.id,
        counterparty_name=counterparty.name,
        positions=positions,
        status=ExposureStatus.UNAVAILABLE,
        detail=detail,
    )


def _compute_exposure(
    counterparty: Counterparty,
    positions: list[Position],
    current_prices: dict[str, float],
    prior_prices: dict[str, float],
    held: float,
    vix: float | None,
    vix_error: str | None,
) -> CounterpartyExposure:
    """Pure computation, no session/DB access -- takes whatever positions
    and prices the caller already fetched (either build_exposure_board's
    whole-board batch, or _counterparty_exposure's single-counterparty
    fetch) so the N+1 fix (MM-66) only has to change how data gets in, not
    the calc/status logic itself."""
    if not positions:
        return _unavailable(counterparty, "No positions on record for this counterparty.", [])

    tickers = sorted({p.ticker for p in positions})

    try:
        mtm_today = compute_mtm(positions, current_prices)
    except PricingError as exc:
        return _unavailable(counterparty, str(exc), [])

    position_exposures = [
        PositionExposure(
            ticker=pm.ticker,
            asset_class=pm.asset_class.value,
            quantity=pm.quantity,
            price=pm.price,
            mtm=pm.mtm,
        )
        for pm in mtm_today.positions
    ]

    if any(t not in prior_prices for t in tickers):
        # Thin seed data (batch_loader has only run once for some tickers) --
        # can't compute a VM swing without a real prior close, but the real
        # positions/prices we do have are still worth showing.
        return _unavailable(
            counterparty,
            "No prior-day close available for one or more positions.",
            position_exposures,
        )

    try:
        csa_terms_result = _csa_terms(counterparty.id)
    except CSATermsUnavailableError as exc:
        return _unavailable(counterparty, str(exc), position_exposures)

    if vix_error is not None:
        return _unavailable(counterparty, vix_error, position_exposures)
    assert vix is not None  # vix_error is None iff vix was fetched successfully

    try:
        mtm_prior = compute_mtm(positions, prior_prices)
        variation_margin = compute_variation_margin(mtm_today, mtm_prior)
        initial_margin = compute_initial_margin(mtm_today, vix)
    except PricingError as exc:
        return _unavailable(counterparty, str(exc), position_exposures)

    exposure = variation_margin.variation_margin + initial_margin.initial_margin
    csa_terms = CSATerms(
        threshold=csa_terms_result.threshold,
        mta=csa_terms_result.mta,
        currency=csa_terms_result.currency,
    )
    breach_result = evaluate_breach(exposure, held, csa_terms)

    return CounterpartyExposure(
        counterparty_id=counterparty.id,
        counterparty_name=counterparty.name,
        positions=position_exposures,
        exposure=exposure,
        threshold=csa_terms.threshold,
        collateral_held=held,
        call_amount=breach_result.call_amount,
        status=_classify_status(exposure, csa_terms, breach_result),
        currency=csa_terms.currency,
    )


def _counterparty_exposure(
    session: Session, counterparty: Counterparty, vix: float | None, vix_error: str | None
) -> CounterpartyExposure:
    """Single-counterparty fetch + compute, used by get_counterparty_exposure
    (MM-61) -- fetching just one counterparty was never the N+1 problem, so
    this keeps its own simple per-counterparty queries rather than reusing
    build_exposure_board's whole-board batch functions."""
    positions = load_positions(session, counterparty.id)
    if not positions:
        return _unavailable(counterparty, "No positions on record for this counterparty.", [])

    tickers = sorted({p.ticker for p in positions})
    now = datetime.now(UTC)
    current_prices = {t: q.price for t, q in latest_prices(session, tickers).items()}
    prior_prices = latest_closes_before(session, tickers, now)
    held = collateral_held(session, counterparty.id)

    return _compute_exposure(
        counterparty, positions, current_prices, prior_prices, held, vix, vix_error
    )


def _fetch_vix(session: Session) -> tuple[float | None, str | None]:
    """(vix, None) on success or (None, error_detail) on failure -- shared
    by build_exposure_board and get_counterparty_exposure (MM-61) so both
    the whole-board and single-counterparty paths use the same
    fetch-once-not-per-counterparty pattern from MM-60."""
    try:
        return latest_vix(session), None
    except PricingError as exc:
        return None, str(exc)


def list_counterparty_summaries(session: Session) -> CounterpartyListResponse:
    """Names-only listing (MM-62) for the Positions & Exposure list page --
    a trivial DB read, deliberately doing none of build_exposure_board's
    per-counterparty price/CSA/VIX computation. Status only ever appears on
    the per-counterparty detail page (get_counterparty_exposure, MM-61)."""
    counterparties = list_counterparties(session)
    return CounterpartyListResponse(
        counterparties=[
            CounterpartySummary(counterparty_id=cp.id, counterparty_name=cp.name)
            for cp in counterparties
        ]
    )


def build_exposure_board(session: Session) -> ExposureBoardResponse:
    counterparties = list_counterparties(session)
    # VIX is a single global market value, not per-counterparty -- fetched
    # once here (MM-60) rather than once per counterparty in the loop
    # below. A failure is identical for every counterparty (same missing
    # reference rate), so it's caught once and threaded through instead of
    # re-raising the same PricingError N times.
    vix, vix_error = _fetch_vix(session)

    # MM-66: positions/prices/prior-closes/collateral are all fetched once
    # for the whole board (one round trip each) instead of once per
    # counterparty -- ~45 SQL round trips down to ~6, regardless of
    # counterparty count. compute_mtm only looks up the tickers a given
    # counterparty actually holds, so handing every counterparty the same
    # superset price dicts is safe -- no per-counterparty filtering needed.
    counterparty_ids = [cp.id for cp in counterparties]
    positions_by_cp = load_positions_for_counterparties(session, counterparty_ids)
    all_tickers = sorted({p.ticker for positions in positions_by_cp.values() for p in positions})
    now = datetime.now(UTC)
    current_prices = {t: q.price for t, q in latest_prices(session, all_tickers).items()}
    prior_prices = latest_closes_before(session, all_tickers, now)
    collateral_by_cp = collateral_held_for_counterparties(session, counterparty_ids)

    items = [
        _compute_exposure(
            cp,
            positions_by_cp.get(cp.id, []),
            current_prices,
            prior_prices,
            collateral_by_cp.get(cp.id, 0.0),
            vix,
            vix_error,
        )
        for cp in counterparties
    ]
    return ExposureBoardResponse(as_of=datetime.now(UTC), counterparties=items)


def get_counterparty_exposure(
    session: Session, counterparty_id: str
) -> CounterpartyExposure | None:
    """Single-counterparty equivalent of build_exposure_board (MM-61) --
    for the detail page, which used to fetch the entire board (every
    counterparty's full price/CSA/VIX computation) just to show one."""
    counterparty = get_counterparty(session, counterparty_id)
    if counterparty is None:
        return None
    vix, vix_error = _fetch_vix(session)
    return _counterparty_exposure(session, counterparty, vix, vix_error)


def get_price_history(session: Session, ticker: str, days: int = 30) -> PriceHistoryResponse:
    entries = price_history_rows(session, ticker, days=days)
    if not entries:
        raise MarketDataUnavailableError(f"No price history available for {ticker}")
    return PriceHistoryResponse(
        ticker=ticker, points=[PricePoint(date=e.date, price=e.price) for e in entries]
    )
