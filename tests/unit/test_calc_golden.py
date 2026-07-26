"""Golden-value suite: chains MTM -> VM -> IM -> breach end-to-end through
real (not mocked) calc functions, against hand-computed expected values at
every stage. This is what "exhaustively tested" means for Phase 2's
financial core (see docs/ROADMAP.md Phase 2 exit criteria).
"""

from datetime import date

from calc.breach import evaluate_breach
from calc.im import compute_initial_margin
from calc.models import CSATerms
from calc.mtm import compute_mtm
from calc.vm import compute_variation_margin
from persistence.models import AssetClass, Position

POSITIONS = [
    Position(
        id="POS-1",
        portfolio_id="PF-GOLD",
        ticker="AAPL",
        asset_class=AssetClass.EQUITY,
        quantity=100,
        trade_date=date(2026, 1, 1),
    ),
    Position(
        id="POS-2",
        portfolio_id="PF-GOLD",
        ticker="SPY",
        asset_class=AssetClass.ETF,
        quantity=50,
        trade_date=date(2026, 1, 1),
    ),
    Position(
        id="POS-3",
        portfolio_id="PF-GOLD",
        ticker="IEF",
        asset_class=AssetClass.ETF,
        quantity=100,
        trade_date=date(2026, 1, 1),
    ),
    Position(
        id="POS-4",
        portfolio_id="PF-GOLD",
        ticker="BTC-USD",
        asset_class=AssetClass.CRYPTO,
        quantity=0.5,
        trade_date=date(2026, 1, 1),
    ),
]

PRICES_TODAY = {"AAPL": 220.0, "SPY": 560.0, "IEF": 98.0, "BTC-USD": 68000.0}
PRICES_PRIOR = {"AAPL": 210.0, "SPY": 550.0, "IEF": 100.0, "BTC-USD": 64000.0}

# Hand-computed MTM today: 100*220 + 50*560 + 100*98 + 0.5*68000
#                        = 22000 + 28000 + 9800 + 34000 = 93800
EXPECTED_MTM_TODAY = 93800.0
# Hand-computed MTM prior: 100*210 + 50*550 + 100*100 + 0.5*64000
#                        = 21000 + 27500 + 10000 + 32000 = 90500
EXPECTED_MTM_PRIOR = 90500.0
# VM = 93800 - 90500 = 3300
EXPECTED_VM = 3300.0
# IM base (VIX=20, multiplier=1.0): 22000*0.15 + 28000*0.10 + 9800*0.02 + 34000*0.30
#                                  = 3300 + 2800 + 196 + 10200 = 16496
EXPECTED_IM = 16496.0
# Exposure = VM + IM = 3300 + 16496 = 19796
EXPECTED_EXPOSURE = 19796.0


def _compute_exposure() -> float:
    mtm_today = compute_mtm(POSITIONS, PRICES_TODAY)
    mtm_prior = compute_mtm(POSITIONS, PRICES_PRIOR)
    assert mtm_today.total_mtm == EXPECTED_MTM_TODAY
    assert mtm_prior.total_mtm == EXPECTED_MTM_PRIOR

    vm = compute_variation_margin(mtm_today, mtm_prior)
    assert vm.variation_margin == EXPECTED_VM

    im = compute_initial_margin(mtm_today, vix_level=20.0)
    assert im.initial_margin == EXPECTED_IM

    exposure = vm.variation_margin + im.initial_margin
    assert exposure == EXPECTED_EXPOSURE
    return exposure


class TestGoldenScenarios:
    def test_no_breach_when_exposure_is_below_threshold(self) -> None:
        exposure = _compute_exposure()

        result = evaluate_breach(
            exposure, collateral_held=0.0, csa_terms=CSATerms(threshold=25000.0, mta=1000.0)
        )

        # required_support = max(0, 19796-25000) = 0 -> no breach
        assert result.breached is False
        assert result.call_amount == 0.0

    def test_no_call_when_shortfall_does_not_clear_mta(self) -> None:
        exposure = _compute_exposure()

        result = evaluate_breach(
            exposure, collateral_held=0.0, csa_terms=CSATerms(threshold=19000.0, mta=2000.0)
        )

        # required_support = 19796-19000 = 796 < mta(2000) -> no breach
        assert result.breached is False
        assert result.call_amount == 0.0

    def test_existing_collateral_reduces_call_to_exactly_the_mta(self) -> None:
        exposure = _compute_exposure()

        result = evaluate_breach(
            exposure,
            collateral_held=3796.0,
            csa_terms=CSATerms(threshold=15000.0, mta=1000.0),
        )

        # required_support = 19796-15000 = 4796; delivery = 4796-3796 = 1000 >= mta(1000)
        assert result.breached is True
        assert result.call_amount == 1000.0

    def test_full_breach_with_no_existing_collateral(self) -> None:
        exposure = _compute_exposure()

        result = evaluate_breach(
            exposure, collateral_held=0.0, csa_terms=CSATerms(threshold=15000.0, mta=1000.0)
        )

        # required_support = 19796-15000 = 4796; delivery = 4796-0 = 4796 >= mta(1000)
        assert result.breached is True
        assert result.call_amount == 4796.0
