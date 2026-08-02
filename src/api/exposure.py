"""Positions & exposure board (MM-52): per-counterparty positions, live
prices, and a deterministic status light (healthy/at_risk/breached/
unavailable), built from the same calc modules the orchestrator uses for a
single margin-call run -- code computes the numbers, never the LLM (golden
rule 1)."""

from datetime import UTC, datetime
from functools import lru_cache

import structlog
from sqlalchemy.orm import Session

from agents.csa_rag import CSATermsUnavailableError, answer_csa_terms
from api.schemas import (
    CounterpartyExposure,
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
from persistence.models import Counterparty
from persistence.queries import collateral_held, latest_vix, list_counterparties, load_positions
from rag.models import CSATermsResult
from streaming.event_agent import latest_close_before
from streaming.market_feed import MarketDataUnavailableError, MarketFeed
from streaming.market_feed import get_price_history as fetch_ticker_price_history

logger = structlog.get_logger()

# A counterparty whose exposure has already reached this fraction of its CSA
# threshold is flagged "at risk" even before it actually breaches -- gives
# the dashboard's amber light somewhere to mean something other than "about
# to turn red at the last possible second".
AT_RISK_THRESHOLD_FRACTION = 0.8


@lru_cache(maxsize=64)
def _cached_csa_terms(counterparty_id: str) -> CSATermsResult:
    """CSA terms are extracted (RAG + LLM) from static demo policy documents
    that don't change during a session -- cached per process so repeated
    exposure-board requests don't re-run extraction for the same
    counterparty on every poll. Distinct from the orchestrator's
    fetch_csa_terms, a one-shot call per margin-call run that deliberately
    stays uncached (correctness there matters more than call volume)."""
    return answer_csa_terms(counterparty_id)


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


def _counterparty_exposure(
    session: Session, counterparty: Counterparty, market_feed: MarketFeed
) -> CounterpartyExposure:
    positions = load_positions(session, counterparty.id)
    if not positions:
        return _unavailable(counterparty, "No positions on record for this counterparty.", [])

    tickers = sorted({p.ticker for p in positions})
    now = datetime.now(UTC)

    try:
        current_prices = {t: q.price for t, q in market_feed.get_prices(tickers).items()}
        mtm_today = compute_mtm(positions, current_prices)
    except (MarketDataUnavailableError, PricingError) as exc:
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

    prior_prices = {
        t: close for t in tickers if (close := latest_close_before(session, t, now)) is not None
    }
    if set(prior_prices) != set(tickers):
        # Thin seed data (batch_loader has only run once for some tickers) --
        # can't compute a VM swing without a real prior close, but the real
        # positions/prices we do have are still worth showing.
        return _unavailable(
            counterparty,
            "No prior-day close available for one or more positions.",
            position_exposures,
        )

    try:
        csa_terms_result = _cached_csa_terms(counterparty.id)
    except CSATermsUnavailableError as exc:
        return _unavailable(counterparty, str(exc), position_exposures)

    try:
        mtm_prior = compute_mtm(positions, prior_prices)
        variation_margin = compute_variation_margin(mtm_today, mtm_prior)
        initial_margin = compute_initial_margin(mtm_today, latest_vix(session))
    except PricingError as exc:
        return _unavailable(counterparty, str(exc), position_exposures)

    exposure = variation_margin.variation_margin + initial_margin.initial_margin
    held = collateral_held(session, counterparty.id)
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


def build_exposure_board(session: Session, market_feed: MarketFeed) -> ExposureBoardResponse:
    counterparties = list_counterparties(session)
    items = [_counterparty_exposure(session, cp, market_feed) for cp in counterparties]
    return ExposureBoardResponse(as_of=datetime.now(UTC), counterparties=items)


def get_price_history(ticker: str, days: int = 30) -> PriceHistoryResponse:
    points = fetch_ticker_price_history(ticker, days=days)
    return PriceHistoryResponse(
        ticker=ticker, points=[PricePoint(date=p.date, price=p.price) for p in points]
    )
