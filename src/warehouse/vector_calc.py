"""Vectorized twins of the calc engine for the warehouse backfill (MM-140).

The backfill evaluates 1,000 counterparties x ~1,260 trading days, so it
works on numpy arrays instead of one pydantic object per position. Every
function here mirrors one scalar function in `calc/` and reuses its
constants and helpers (risk weights, the VIX multiplier, rating order);
tests/unit/test_warehouse_vector_calc.py proves each one equals its scalar
twin on randomised books. The arithmetic is done in the same order as the
scalar code (sum today, sum prior, subtract; sum |MTM| x weight, multiply),
so results match to floating-point rounding.

One addition with no scalar twin in calc/: `return_amounts`, the CSA Return
Amount (excess collateral handed back), which the live app leaves out of
scope. The backfill needs it so collateral doesn't only ratchet up over five
years; `return_amount` is its scalar reference.
"""

import numpy as np
from numpy.typing import NDArray

from calc.im import risk_weight, vix_multiplier
from persistence.models import RATING_ORDER, AssetClass, RatingGrade

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]
BoolArray = NDArray[np.bool_]

# Rating rank as calc.breach compares it: index in RATING_ORDER (0 = AAA).
# NO_TRIGGER_RANK is beyond D, so no rating is ever "below" it.
RATING_RANK: dict[RatingGrade, int] = {grade: i for i, grade in enumerate(RATING_ORDER)}
NO_TRIGGER_RANK = len(RATING_ORDER)


def risk_weights(tickers: list[str], asset_classes: list[AssetClass]) -> FloatArray:
    """calc.im.risk_weight per position."""
    return np.array([risk_weight(t, a) for t, a in zip(tickers, asset_classes, strict=True)])


def portfolio_mtm(
    cp_index: IntArray, quantity: FloatArray, price: FloatArray, n: int
) -> FloatArray:
    """calc.mtm.compute_mtm(...).total_mtm for every counterparty at once.
    Positions with a NaN price must be excluded by the caller (the scalar
    function raises on them)."""
    return np.bincount(cp_index, weights=quantity * price, minlength=n).astype(np.float64)


def variation_margin(mtm_today: FloatArray, mtm_prior: FloatArray) -> FloatArray:
    """calc.vm.compute_variation_margin(...).variation_margin."""
    return mtm_today - mtm_prior


def initial_margin(
    cp_index: IntArray,
    quantity: FloatArray,
    price: FloatArray,
    weight: FloatArray,
    vix: float,
    n: int,
) -> FloatArray:
    """calc.im.compute_initial_margin(...).initial_margin for every counterparty."""
    base = np.bincount(cp_index, weights=np.abs(quantity * price) * weight, minlength=n)
    return (base * vix_multiplier(vix)).astype(np.float64)


def effective_threshold(
    threshold: FloatArray,
    rating_rank: IntArray,
    trigger_rank: IntArray,
    trigger_threshold: FloatArray,
) -> FloatArray:
    """calc.breach.effective_threshold for one trigger per CSA: the reduced
    threshold applies once the rating is strictly below the trigger grade.
    rating_rank < 0 means no rating (no trigger fires)."""
    fired = (rating_rank >= 0) & (rating_rank > trigger_rank)
    return np.where(fired, trigger_threshold, threshold)


def evaluate_breach(
    exposure: FloatArray, collateral: FloatArray, threshold: FloatArray, mta: FloatArray
) -> tuple[BoolArray, FloatArray, FloatArray]:
    """calc.breach.evaluate_breach -> (breached, call_amount, required_support)."""
    required = np.maximum(0.0, exposure - threshold)
    delivery = required - collateral
    breached = (delivery > 0) & (delivery >= mta)
    return breached, np.where(breached, delivery, 0.0), required


def return_amount(collateral: float, required_support: float, mta: float) -> float:
    """CSA Return Amount (scalar reference): collateral held beyond the
    credit support required is returned, if the excess clears the MTA."""
    excess = collateral - required_support
    return excess if excess > 0 and excess >= mta else 0.0


def return_amounts(collateral: FloatArray, required: FloatArray, mta: FloatArray) -> FloatArray:
    excess = collateral - required
    return np.where((excess > 0) & (excess >= mta), excess, 0.0)
