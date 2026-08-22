"""Post-processing collateral calibration (MM-77). collateral.py's initial
seed (used at generate_all() time, before any prices exist) is a flat random
range with no notion of portfolio size -- most counterparties end up either
wildly over- or under-collateralized relative to their own exposure. This
module runs *after* prices/VIX are loaded (batch_loader wires it in after
load_prices/backfill_price_history) and replaces each counterparty's
collateral with a single amount scaled to a random 40-70% of that
counterparty's own real exposure -- computed via the same VM+IM pipeline
api/exposure.py uses, reimplemented here rather than imported from api/ to
avoid persistence/ depending on the api layer."""

import random
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.orm import Session

from calc.im import compute_initial_margin
from calc.models import PricingError
from calc.mtm import compute_mtm
from calc.vm import compute_variation_margin
from persistence.db.models import CollateralItemORM
from persistence.models import CollateralType
from persistence.queries import (
    latest_closes_before,
    latest_vix,
    list_counterparties,
    load_positions,
)

MIN_FACTOR = 0.4
MAX_FACTOR = 0.7
# A floor, not a typical value -- only matters for a counterparty whose
# computed exposure happens to be negative or near-zero (a real possibility:
# calc/im.py's IM is abs()-based but VM is signed, so a short position that
# moved favorably can net a negative exposure). Real collateral is never
# negative, so this keeps the calibrated value sane in that edge case
# without distorting the vast majority of counterparties where exposure is
# comfortably positive.
MIN_COLLATERAL_USD = 10_000.0


def _counterparty_exposure(
    session: Session, counterparty_id: str, vix: float, as_of: date
) -> float | None:
    """Real VM+IM exposure for one counterparty, or None if it can't be
    computed (no positions, a ticker missing a current or prior price).
    Deliberately sources both "current" and "prior" prices from
    PriceHistoryORM via two latest_closes_before() calls at different
    cutoffs, not persistence.queries.latest_prices() -- that table
    (LatestPriceORM) is only populated by the live-feed poller's Kafka
    ticks, a separate running process batch_loader can't assume is up. Using
    PriceHistoryORM instead ties this purely to what load_prices/
    backfill_price_history just wrote, a few lines above in batch_loader.py."""
    positions = load_positions(session, counterparty_id)
    if not positions:
        return None

    tickers = sorted({p.ticker for p in positions})
    as_of_dt = datetime.combine(as_of, datetime.min.time(), tzinfo=UTC)
    current_prices = latest_closes_before(session, tickers, as_of_dt + timedelta(days=1))
    prior_prices = latest_closes_before(session, tickers, as_of_dt)

    if any(t not in current_prices for t in tickers) or any(t not in prior_prices for t in tickers):
        return None

    try:
        mtm_today = compute_mtm(positions, current_prices)
        mtm_prior = compute_mtm(positions, prior_prices)
        vm = compute_variation_margin(mtm_today, mtm_prior)
        im = compute_initial_margin(mtm_today, vix)
    except PricingError:
        return None

    return vm.variation_margin + im.initial_margin


def calibrate_collateral_to_exposure(session: Session, seed: int, as_of: date) -> dict[str, float]:
    """Replaces every counterparty's collateral rows with a single cash item
    (0% haircut, so the stored value_usd equals collateral_held with no
    haircut math to reason about) valued at a seeded-random 40-70% of that
    counterparty's own real exposure. Deterministic given the same seed,
    matching the rest of this package's generators. A counterparty whose
    exposure can't be computed (missing prices, no positions) is left
    untouched rather than zeroed -- its existing collateral rows stay as-is.
    Returns the new collateral value per counterparty that was actually
    recalibrated, for logging/verification."""
    rng = random.Random(seed)

    try:
        vix = latest_vix(session)
    except PricingError:
        return {}

    results: dict[str, float] = {}
    for counterparty in sorted(list_counterparties(session), key=lambda c: c.id):
        exposure = _counterparty_exposure(session, counterparty.id, vix, as_of)
        if exposure is None:
            continue

        factor = rng.uniform(MIN_FACTOR, MAX_FACTOR)
        target = max(MIN_COLLATERAL_USD, exposure * factor)

        session.execute(
            delete(CollateralItemORM).where(CollateralItemORM.counterparty_id == counterparty.id)
        )
        session.add(
            CollateralItemORM(
                id=f"COL-CALIB-{counterparty.id}",
                counterparty_id=counterparty.id,
                collateral_type=CollateralType.CASH.value,
                value_usd=target,
                haircut_pct=0.0,
            )
        )
        results[counterparty.id] = target

    session.commit()
    return results
