"""Phase 7 golden-value suite (MM-49): chains the deterministic pieces --
trade-diff -> reconcile -> collateral optimizer -- end to end through real
(not mocked) functions, against hand-computed expected values at every
stage. Mirrors test_calc_golden.py's spirit for Phase 2. The Reconciliation
Agent's LLM-drafted rationale (MM-47) isn't part of this chain, same reason
test_calc_golden.py never touches an LLM either -- golden-value suites
verify deterministic math, not model prose.
"""

from datetime import date

from calc.collateral_optimizer import InventoryItem, optimize_collateral
from calc.trade_diff import BreakType, diff_trades, reconcile
from persistence.models import AssetClass, Position


def _position(id_: str, ticker: str, quantity: float) -> Position:
    return Position(
        id=id_,
        portfolio_id="PF-GOLD",
        ticker=ticker,
        asset_class=AssetClass.EQUITY,
        quantity=quantity,
        trade_date=date(2026, 1, 1),
    )


OUR_POSITIONS = [
    _position("POS-1", "AAPL", 100.0),
    _position("POS-2", "MSFT", 50.0),
    _position("POS-3", "TSLA", 25.0),
]

# Counterparty view, hand-built (not the seeded perturbation generator) so
# every break in this golden scenario is exactly known up front: AAPL
# matches, MSFT is quantity-mismatched, TSLA is missing entirely.
COUNTERPARTY_POSITIONS = [
    _position("CPTY-1", "AAPL", 100.0),
    _position("CPTY-2", "MSFT", 40.0),
]

OUR_TOTAL = 500_000.0
COUNTERPARTY_TOTAL = 400_000.0
TOLERANCE = 1_000.0
# Disagreement = 500,000 - 400,000 = 100,000
EXPECTED_DISAGREEMENT = 100_000.0

ELIGIBLE_COLLATERAL = ["cash", "security"]
HAIRCUTS = {"cash": 0.0, "security": 0.2}
INVENTORY = [
    InventoryItem(collateral_type="cash", available_value_usd=30_000.0),
    InventoryItem(collateral_type="security", available_value_usd=200_000.0),
]


class TestPhase7GoldenScenario:
    def test_diff_trades_isolates_exactly_the_two_known_breaks(self) -> None:
        breaks = diff_trades(OUR_POSITIONS, COUNTERPARTY_POSITIONS)

        by_ticker = {b.ticker: b for b in breaks}
        assert set(by_ticker) == {"MSFT", "TSLA"}
        assert by_ticker["MSFT"].break_type == BreakType.QUANTITY_MISMATCH
        assert by_ticker["MSFT"].our_quantity == 50.0
        assert by_ticker["MSFT"].counterparty_quantity == 40.0
        assert by_ticker["TSLA"].break_type == BreakType.MISSING_IN_COUNTERPARTY_VIEW
        assert by_ticker["TSLA"].our_quantity == 25.0

    def test_reconcile_disagrees_beyond_tolerance(self) -> None:
        result = reconcile(
            OUR_POSITIONS, COUNTERPARTY_POSITIONS, OUR_TOTAL, COUNTERPARTY_TOTAL, TOLERANCE
        )

        assert result.agreed is False
        assert len(result.break_items) == 2
        assert OUR_TOTAL - COUNTERPARTY_TOTAL == EXPECTED_DISAGREEMENT

    def test_optimizer_covers_the_disagreement_with_cheapest_collateral_first(self) -> None:
        result = optimize_collateral(
            EXPECTED_DISAGREEMENT, ELIGIBLE_COLLATERAL, HAIRCUTS, INVENTORY
        )

        # Hand-computed: cash (0% haircut) drawn first, fully exhausted at
        # $30,000 -> $30,000 credit. Remaining $70,000 needed from security
        # (20% haircut): raw_needed = 70,000 / 0.8 = 87,500 -> $70,000 credit.
        assert result.fully_funded is True
        assert len(result.proposed_collateral) == 2
        assert result.proposed_collateral[0].collateral_type == "cash"
        assert result.proposed_collateral[0].value_usd == 30_000.0
        assert result.proposed_collateral[0].post_haircut_value == 30_000.0
        assert result.proposed_collateral[1].collateral_type == "security"
        assert result.proposed_collateral[1].value_usd == 87_500.0
        assert result.proposed_collateral[1].post_haircut_value == 70_000.0
        assert result.post_haircut_value == EXPECTED_DISAGREEMENT
