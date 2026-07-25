import random

from persistence.generators.securities import TREASURY_ETF_TICKERS
from persistence.models import CollateralItem, CollateralType

MIN_ITEMS_PER_COUNTERPARTY = 1
MAX_ITEMS_PER_COUNTERPARTY = 3
MIN_CASH_VALUE = 100_000
MAX_CASH_VALUE = 5_000_000
MIN_SECURITY_VALUE = 50_000
MAX_SECURITY_VALUE = 2_000_000
CASH_HAIRCUT_PCT = 0.0
TREASURY_HAIRCUT_PCT = 0.005
SECURITY_ITEM_CHANCE = 0.5


def _cash_item(item_id: str, cp_id: str, rng: random.Random) -> CollateralItem:
    return CollateralItem(
        id=item_id,
        counterparty_id=cp_id,
        collateral_type=CollateralType.CASH,
        value_usd=float(rng.randint(MIN_CASH_VALUE, MAX_CASH_VALUE)),
        haircut_pct=CASH_HAIRCUT_PCT,
    )


def _security_item(
    item_id: str, cp_id: str, rng: random.Random, tickers: list[str]
) -> CollateralItem:
    return CollateralItem(
        id=item_id,
        counterparty_id=cp_id,
        collateral_type=CollateralType.SECURITY,
        ticker=rng.choice(tickers),
        value_usd=float(rng.randint(MIN_SECURITY_VALUE, MAX_SECURITY_VALUE)),
        haircut_pct=TREASURY_HAIRCUT_PCT,
    )


def generate_collateral(rng: random.Random, counterparty_ids: list[str]) -> list[CollateralItem]:
    treasury_tickers = sorted(TREASURY_ETF_TICKERS)
    items: list[CollateralItem] = []
    counter = 1

    for cp_id in counterparty_ids:
        num_items = rng.randint(MIN_ITEMS_PER_COUNTERPARTY, MAX_ITEMS_PER_COUNTERPARTY)

        items.append(_cash_item(f"COL-{counter}", cp_id, rng))
        counter += 1

        for _ in range(num_items - 1):
            if rng.random() < SECURITY_ITEM_CHANCE:
                items.append(_security_item(f"COL-{counter}", cp_id, rng, treasury_tickers))
            else:
                items.append(_cash_item(f"COL-{counter}", cp_id, rng))
            counter += 1

    return items
