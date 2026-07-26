import pytest

from calc.models import PortfolioMTM, PositionMTM, PricingError
from calc.vm import compute_variation_margin
from persistence.models import AssetClass


def _portfolio_mtm(portfolio_id: str, total_mtm: float) -> PortfolioMTM:
    return PortfolioMTM(
        portfolio_id=portfolio_id,
        positions=[
            PositionMTM(
                position_id="POS-1",
                ticker="AAPL",
                asset_class=AssetClass.EQUITY,
                quantity=1,
                price=total_mtm,
                mtm=total_mtm,
            )
        ],
        total_mtm=total_mtm,
    )


class TestComputeVariationMargin:
    def test_positive_variation_margin_on_price_rise(self) -> None:
        today = _portfolio_mtm("PF-1", 48500.0)
        prior = _portfolio_mtm("PF-1", 45000.0)

        result = compute_variation_margin(today, prior)

        # Hand-computed: 48500 - 45000 = 3500
        assert result.variation_margin == 3500.0
        assert result.mtm_today == 48500.0
        assert result.mtm_prior == 45000.0
        assert result.portfolio_id == "PF-1"

    def test_negative_variation_margin_on_price_drop(self) -> None:
        today = _portfolio_mtm("PF-1", 40000.0)
        prior = _portfolio_mtm("PF-1", 45000.0)

        result = compute_variation_margin(today, prior)

        assert result.variation_margin == -5000.0

    def test_zero_variation_margin_when_unchanged(self) -> None:
        today = _portfolio_mtm("PF-1", 45000.0)
        prior = _portfolio_mtm("PF-1", 45000.0)

        result = compute_variation_margin(today, prior)

        assert result.variation_margin == 0.0

    def test_mismatched_portfolio_raises(self) -> None:
        today = _portfolio_mtm("PF-1", 48500.0)
        prior = _portfolio_mtm("PF-2", 45000.0)

        with pytest.raises(PricingError, match="same portfolio"):
            compute_variation_margin(today, prior)
