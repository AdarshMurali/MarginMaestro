"""MM-140: the backfill's vectorized calc equals the scalar calc engine.

Randomised books (seeded, so reproducible): every counterparty's VM, IM,
effective threshold and breach from warehouse.vector_calc is compared with
calc.mtm / calc.vm / calc.im / calc.breach run one counterparty at a time.
"""

from datetime import date

import numpy as np
import pytest

from calc.breach import effective_threshold, evaluate_breach
from calc.im import compute_initial_margin
from calc.models import CSATerms, PricingError
from calc.mtm import compute_mtm
from calc.vm import compute_variation_margin
from persistence.models import RATING_ORDER, AssetClass, Position, RatingTrigger
from warehouse import vector_calc as vc

TICKERS = ["AAPL", "MSFT", "SPY", "TLT", "IEF", "BTC-USD", "JPM", "XOM"]
CLASSES = {
    "SPY": AssetClass.ETF,
    "TLT": AssetClass.ETF,
    "IEF": AssetClass.ETF,
    "BTC-USD": AssetClass.CRYPTO,
}
SEEDS = range(25)


def _book(seed: int):
    rng = np.random.default_rng(seed)
    n = int(rng.integers(1, 12))
    positions, cp_index = [], []
    for cp in range(n):
        for k, ticker in enumerate(
            rng.choice(TICKERS, size=int(rng.integers(1, 6)), replace=False)
        ):
            quantity = float(rng.integers(-2_000, 2_000) or 1)
            positions.append(
                Position(
                    id=f"P{cp}-{k}",
                    portfolio_id=f"PF-{cp}",
                    ticker=str(ticker),
                    asset_class=CLASSES.get(str(ticker), AssetClass.EQUITY),
                    quantity=quantity,
                    trade_date=date(2024, 1, 1),
                )
            )
            cp_index.append(cp)
    today = {t: float(rng.uniform(5, 900)) for t in TICKERS}
    prior = {t: today[t] * float(rng.uniform(0.85, 1.15)) for t in TICKERS}
    vix = float(rng.uniform(5, 90))
    return rng, n, positions, np.array(cp_index), today, prior, vix


@pytest.mark.parametrize("seed", SEEDS)
def test_vm_and_im_equal_the_scalar_engine(seed):
    _, n, positions, cp_index, today, prior, vix = _book(seed)
    qty = np.array([p.quantity for p in positions])
    p_today = np.array([today[p.ticker] for p in positions])
    p_prior = np.array([prior[p.ticker] for p in positions])
    weights = vc.risk_weights([p.ticker for p in positions], [p.asset_class for p in positions])

    vm = vc.variation_margin(
        vc.portfolio_mtm(cp_index, qty, p_today, n), vc.portfolio_mtm(cp_index, qty, p_prior, n)
    )
    im = vc.initial_margin(cp_index, qty, p_today, weights, vix, n)

    for cp in range(n):
        book = [p for p in positions if p.portfolio_id == f"PF-{cp}"]
        mtm_today = compute_mtm(book, today)
        expected_vm = compute_variation_margin(mtm_today, compute_mtm(book, prior))
        expected_im = compute_initial_margin(mtm_today, vix)
        assert vm[cp] == pytest.approx(expected_vm.variation_margin, rel=1e-12, abs=1e-6)
        assert im[cp] == pytest.approx(expected_im.initial_margin, rel=1e-12, abs=1e-6)


@pytest.mark.parametrize("seed", SEEDS)
def test_thresholds_and_breaches_equal_the_scalar_engine(seed):
    rng = np.random.default_rng(1_000 + seed)
    n = 50
    grades = RATING_ORDER
    threshold = rng.choice([0.0, 50_000.0, 250_000.0, 500_000.0], size=n)
    mta = rng.choice([0.0, 10_000.0, 50_000.0], size=n)
    trigger = rng.integers(0, len(grades), size=n)
    reduced = rng.choice([0.0, 25_000.0], size=n)
    rating = rng.integers(-1, len(grades), size=n)  # -1 = no rating
    exposure = rng.uniform(-200_000, 1_500_000, size=n)
    collateral = rng.uniform(0, 600_000, size=n)

    effective = vc.effective_threshold(threshold, rating, trigger, reduced)
    breached, call, required = vc.evaluate_breach(exposure, collateral, effective, mta)

    for i in range(n):
        terms = CSATerms(
            threshold=float(threshold[i]),
            mta=float(mta[i]),
            rating_triggers=[
                RatingTrigger(below_grade=grades[trigger[i]], reduced_threshold=float(reduced[i]))
            ],
        )
        current = grades[rating[i]] if rating[i] >= 0 else None
        assert effective[i] == effective_threshold(terms, current)
        expected = evaluate_breach(float(exposure[i]), float(collateral[i]), terms, current)
        assert bool(breached[i]) is expected.breached
        assert call[i] == pytest.approx(expected.call_amount)
        assert required[i] == pytest.approx(max(0.0, exposure[i] - effective[i]))


def test_a_counterparty_without_positions_has_zero_exposure():
    cp = np.array([0, 0])
    qty = np.array([10.0, -5.0])
    price = np.array([100.0, 40.0])
    weights = np.array([0.15, 0.15])
    assert list(vc.portfolio_mtm(cp, qty, price, 3)) == [800.0, 0.0, 0.0]
    assert vc.initial_margin(cp, qty, price, weights, 20.0, 3)[2] == 0.0


def test_vix_must_be_positive_like_the_scalar_engine():
    with pytest.raises(PricingError):
        vc.initial_margin(np.array([0]), np.array([1.0]), np.array([1.0]), np.array([0.15]), 0.0, 1)


@pytest.mark.parametrize(
    ("collateral", "required", "mta", "expected"),
    [
        (100_000.0, 60_000.0, 10_000.0, 40_000.0),  # excess clears the MTA: returned
        (100_000.0, 95_000.0, 10_000.0, 0.0),  # excess below the MTA: kept
        (50_000.0, 60_000.0, 0.0, 0.0),  # a shortfall is never "returned"
        (60_000.0, 60_000.0, 0.0, 0.0),  # exactly covered
        (70_000.0, 60_000.0, 10_000.0, 10_000.0),  # excess equal to the MTA
    ],
)
def test_return_amount(collateral, required, mta, expected):
    assert vc.return_amount(collateral, required, mta) == expected
    vector = vc.return_amounts(np.array([collateral]), np.array([required]), np.array([mta]))
    assert vector[0] == expected
