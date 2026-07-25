import random
from datetime import date, timedelta

from persistence.generators.securities import asset_class_for, securities_universe
from persistence.models import Portfolio, Position

MIN_POSITIONS_PER_PORTFOLIO = 8
MAX_POSITIONS_PER_PORTFOLIO = 12
MIN_QUANTITY = -500
MAX_QUANTITY = 1000
TRADE_DATE_LOOKBACK_DAYS = 730


def generate_portfolios_and_positions(
    rng: random.Random, counterparty_ids: list[str], as_of: date
) -> tuple[list[Portfolio], list[Position]]:
    universe = securities_universe()
    portfolios: list[Portfolio] = []
    positions: list[Position] = []
    position_counter = 1

    for i, cp_id in enumerate(counterparty_ids, start=1):
        portfolio = Portfolio(id=f"PF-{i}", counterparty_id=cp_id)
        portfolios.append(portfolio)

        num_positions = rng.randint(MIN_POSITIONS_PER_PORTFOLIO, MAX_POSITIONS_PER_PORTFOLIO)
        for ticker in rng.sample(universe, k=num_positions):
            quantity = rng.randint(MIN_QUANTITY, MAX_QUANTITY)
            while quantity == 0:
                quantity = rng.randint(MIN_QUANTITY, MAX_QUANTITY)
            trade_date = as_of - timedelta(days=rng.randint(0, TRADE_DATE_LOOKBACK_DAYS))
            positions.append(
                Position(
                    id=f"POS-{position_counter}",
                    portfolio_id=portfolio.id,
                    ticker=ticker,
                    asset_class=asset_class_for(ticker),
                    quantity=float(quantity),
                    trade_date=trade_date,
                )
            )
            position_counter += 1

    return portfolios, positions
