import pytest

from calc.im import compute_initial_margin
from calc.models import PortfolioMTM, PositionMTM, PricingError
from persistence.models import AssetClass


def _mixed_portfolio() -> PortfolioMTM:
    return PortfolioMTM(
        portfolio_id="PF-1",
        positions=[
            PositionMTM(
                position_id="POS-1",
                ticker="AAPL",
                asset_class=AssetClass.EQUITY,
                quantity=100,
                price=210.0,
                mtm=21000.0,
            ),
            PositionMTM(
                position_id="POS-2",
                ticker="SPY",
                asset_class=AssetClass.ETF,
                quantity=50,
                price=550.0,
                mtm=27500.0,
            ),
            PositionMTM(
                position_id="POS-3",
                ticker="IEF",
                asset_class=AssetClass.ETF,
                quantity=100,
                price=100.0,
                mtm=10000.0,
            ),
        ],
        total_mtm=58500.0,
    )


class TestComputeInitialMargin:
    def test_applies_asset_class_and_treasury_etf_risk_weights_at_baseline_vix(self) -> None:
        result = compute_initial_margin(_mixed_portfolio(), vix_level=20.0)

        # Hand-computed: 21000*0.15 (equity) + 27500*0.10 (ETF) + 10000*0.02 (Treasury ETF)
        # = 3150 + 2750 + 200 = 6100; VIX=20 -> multiplier 1.0 -> IM = 6100
        assert result.vix_multiplier == 1.0
        assert result.initial_margin == 6100.0
        assert result.portfolio_id == "PF-1"

    def test_scales_up_with_elevated_vix(self) -> None:
        result = compute_initial_margin(_mixed_portfolio(), vix_level=40.0)

        # multiplier = 40/20 = 2.0 -> IM = 6100 * 2.0 = 12200
        assert result.vix_multiplier == 2.0
        assert result.initial_margin == 12200.0

    def test_multiplier_is_floored_in_very_calm_markets(self) -> None:
        result = compute_initial_margin(_mixed_portfolio(), vix_level=5.0)

        # 5/20 = 0.25, floored to 0.5 -> IM = 6100 * 0.5 = 3050
        assert result.vix_multiplier == 0.5
        assert result.initial_margin == 3050.0

    def test_multiplier_is_capped_in_extreme_stress(self) -> None:
        result = compute_initial_margin(_mixed_portfolio(), vix_level=100.0)

        # 100/20 = 5.0, capped to 3.0 -> IM = 6100 * 3.0 = 18300
        assert result.vix_multiplier == 3.0
        assert result.initial_margin == 18300.0

    def test_crypto_risk_weight_and_short_position_use_absolute_notional(self) -> None:
        portfolio = PortfolioMTM(
            portfolio_id="PF-2",
            positions=[
                PositionMTM(
                    position_id="POS-1",
                    ticker="BTC-USD",
                    asset_class=AssetClass.CRYPTO,
                    quantity=1,
                    price=50000.0,
                    mtm=50000.0,
                ),
                PositionMTM(
                    position_id="POS-2",
                    ticker="AAPL",
                    asset_class=AssetClass.EQUITY,
                    quantity=-100,
                    price=210.0,
                    mtm=-21000.0,
                ),
            ],
            total_mtm=29000.0,
        )

        result = compute_initial_margin(portfolio, vix_level=20.0)

        # 50000*0.30 (crypto) + abs(-21000)*0.15 (short equity) = 15000 + 3150 = 18150
        assert result.initial_margin == 18150.0

    def test_non_positive_vix_raises(self) -> None:
        with pytest.raises(PricingError, match="vix_level"):
            compute_initial_margin(_mixed_portfolio(), vix_level=0.0)
