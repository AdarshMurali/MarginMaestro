from calc.models import InitialMargin, PortfolioMTM, PricingError
from persistence.generators.securities import TREASURY_ETF_TICKERS
from persistence.models import AssetClass

# Documented SIMM *proxy*, not a certified ISDA SIMM engine -- directionally
# correct only, per docs/adr/0005 (LLM for reasoning, code for math) and
# CLAUDE.md golden rule 1. Notional x risk weight, scaled by a VIX multiplier.
RISK_WEIGHTS: dict[AssetClass, float] = {
    AssetClass.EQUITY: 0.15,
    AssetClass.ETF: 0.10,
    AssetClass.CRYPTO: 0.30,
}
TREASURY_ETF_RISK_WEIGHT = 0.02

VIX_BASELINE = 20.0
VIX_MULTIPLIER_FLOOR = 0.5
VIX_MULTIPLIER_CAP = 3.0


def _risk_weight(ticker: str, asset_class: AssetClass) -> float:
    if ticker in TREASURY_ETF_TICKERS:
        return TREASURY_ETF_RISK_WEIGHT
    return RISK_WEIGHTS[asset_class]


def compute_initial_margin(mtm: PortfolioMTM, vix_level: float) -> InitialMargin:
    if vix_level <= 0:
        raise PricingError(f"vix_level must be positive, got {vix_level}")

    multiplier = max(VIX_MULTIPLIER_FLOOR, min(VIX_MULTIPLIER_CAP, vix_level / VIX_BASELINE))

    base_im = sum(
        abs(position.mtm) * _risk_weight(position.ticker, position.asset_class)
        for position in mtm.positions
    )

    return InitialMargin(
        portfolio_id=mtm.portfolio_id,
        vix_level=vix_level,
        vix_multiplier=multiplier,
        initial_margin=base_im * multiplier,
    )
