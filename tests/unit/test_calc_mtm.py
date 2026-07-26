from datetime import date

import pytest

from calc.models import PricingError
from calc.mtm import compute_mtm
from persistence.models import AssetClass, Position


def _position(
    position_id: str, ticker: str, quantity: float, asset_class=AssetClass.EQUITY
) -> Position:
    return Position(
        id=position_id,
        portfolio_id="PF-1",
        ticker=ticker,
        asset_class=asset_class,
        quantity=quantity,
        trade_date=date(2026, 1, 1),
    )


class TestComputeMtm:
    def test_computes_per_position_and_total_mtm(self) -> None:
        positions = [_position("POS-1", "AAPL", 100), _position("POS-2", "SPY", 50)]
        prices = {"AAPL": 210.0, "SPY": 550.0}

        result = compute_mtm(positions, prices)

        assert result.portfolio_id == "PF-1"
        assert {p.position_id: p.mtm for p in result.positions} == {
            "POS-1": 21000.0,
            "POS-2": 27500.0,
        }
        # Hand-computed: 100 * 210 + 50 * 550 = 21000 + 27500 = 48500
        assert result.total_mtm == 48500.0

    def test_negative_quantity_is_a_valid_short_position(self) -> None:
        positions = [_position("POS-1", "AAPL", -100)]
        prices = {"AAPL": 210.0}

        result = compute_mtm(positions, prices)

        assert result.total_mtm == -21000.0

    def test_empty_positions_raises(self) -> None:
        with pytest.raises(PricingError, match="empty"):
            compute_mtm([], {"AAPL": 210.0})

    def test_mismatched_portfolio_raises(self) -> None:
        positions = [_position("POS-1", "AAPL", 100)]
        positions.append(
            Position(
                id="POS-2",
                portfolio_id="PF-2",
                ticker="SPY",
                asset_class=AssetClass.ETF,
                quantity=10,
                trade_date=date(2026, 1, 1),
            )
        )

        with pytest.raises(PricingError, match="single portfolio"):
            compute_mtm(positions, {"AAPL": 210.0, "SPY": 550.0})

    def test_missing_price_raises(self) -> None:
        positions = [_position("POS-1", "AAPL", 100), _position("POS-2", "SPY", 50)]

        with pytest.raises(PricingError, match="SPY"):
            compute_mtm(positions, {"AAPL": 210.0})
