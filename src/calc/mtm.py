from calc.models import PortfolioMTM, PositionMTM, PricingError
from persistence.models import Position


def compute_mtm(positions: list[Position], prices: dict[str, float]) -> PortfolioMTM:
    """Mark-to-market value of a single portfolio's positions: quantity x price.

    No derivatives/options pricing -- matches this project's plain-position
    data model (see docs/DATA_SOURCES.md).
    """
    if not positions:
        raise PricingError("Cannot compute MTM for an empty position list")

    portfolio_id = positions[0].portfolio_id
    mismatched = [p.id for p in positions if p.portfolio_id != portfolio_id]
    if mismatched:
        raise PricingError(
            "compute_mtm expects positions from a single portfolio; "
            f"found mismatched portfolio_id on positions: {mismatched}"
        )

    position_mtms: list[PositionMTM] = []
    missing_tickers: list[str] = []
    for position in positions:
        price = prices.get(position.ticker)
        if price is None:
            missing_tickers.append(position.ticker)
            continue
        position_mtms.append(
            PositionMTM(
                position_id=position.id,
                ticker=position.ticker,
                quantity=position.quantity,
                price=price,
                mtm=position.quantity * price,
            )
        )

    if missing_tickers:
        raise PricingError(f"No price available for tickers: {', '.join(missing_tickers)}")

    total_mtm = sum(pm.mtm for pm in position_mtms)
    return PortfolioMTM(portfolio_id=portfolio_id, positions=position_mtms, total_mtm=total_mtm)
