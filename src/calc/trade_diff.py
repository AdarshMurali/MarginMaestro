"""Trade-diff engine (MM-46, docs/AGENTS.md #4 Reconciliation & Dispute
Agent): deterministic comparison between our position list and a synthetic
"counterparty view" -- isolates trade-level breaks. No LLM here; the
Reconciliation Agent (MM-47) layers rationale-drafting on top.

There's no real counterparty system in this demo, so `generate_counterparty_view`
simulates one by seeded, reproducible perturbation of our own book -- same
spirit as MM-30's market simulator."""

import random
from enum import Enum

from pydantic import BaseModel

from persistence.models import Position

DEFAULT_SEED = 42
QUANTITY_EPSILON = 1e-9


class BreakType(str, Enum):
    QUANTITY_MISMATCH = "quantity_mismatch"
    MISSING_IN_COUNTERPARTY_VIEW = "missing_in_counterparty_view"
    EXTRA_IN_COUNTERPARTY_VIEW = "extra_in_counterparty_view"


class BreakItem(BaseModel):
    ticker: str
    break_type: BreakType
    our_quantity: float | None
    counterparty_quantity: float | None


class ReconciliationResult(BaseModel):
    agreed: bool
    break_items: list[BreakItem]


def generate_counterparty_view(
    positions: list[Position], seed: int = DEFAULT_SEED
) -> list[Position]:
    """Deterministic, seeded perturbation of our position list, simulating a
    counterparty's (possibly stale/mismatched) view of the same book. Per
    position: ~15% dropped entirely, ~15% quantity mismatched, the rest
    copied unchanged. Also a ~20% chance of one extra trade the counterparty
    believes exists but we don't have."""
    rng = random.Random(seed)
    view: list[Position] = []
    for position in positions:
        roll = rng.random()
        if roll < 0.15:
            continue
        if roll < 0.30:
            view.append(
                position.model_copy(update={"quantity": position.quantity * rng.uniform(0.7, 1.3)})
            )
        else:
            view.append(position.model_copy())

    if positions and rng.random() < 0.2:
        base = positions[0]
        extra_ticker = "AAPL" if base.ticker != "AAPL" else "MSFT"
        view.append(
            base.model_copy(
                update={
                    "id": f"{base.id}-CPTY-EXTRA",
                    "ticker": extra_ticker,
                    "quantity": rng.uniform(10, 100),
                }
            )
        )
    return view


def diff_trades(
    our_positions: list[Position], counterparty_positions: list[Position]
) -> list[BreakItem]:
    """Trade-level diff, keyed by ticker (matches this project's plain
    one-position-per-ticker demo data model, per docs/DATA_SOURCES.md)."""
    our_by_ticker = {p.ticker: p.quantity for p in our_positions}
    cpty_by_ticker = {p.ticker: p.quantity for p in counterparty_positions}

    breaks: list[BreakItem] = []
    for ticker, our_qty in our_by_ticker.items():
        cpty_qty = cpty_by_ticker.get(ticker)
        if cpty_qty is None:
            breaks.append(
                BreakItem(
                    ticker=ticker,
                    break_type=BreakType.MISSING_IN_COUNTERPARTY_VIEW,
                    our_quantity=our_qty,
                    counterparty_quantity=None,
                )
            )
        elif abs(cpty_qty - our_qty) > QUANTITY_EPSILON:
            breaks.append(
                BreakItem(
                    ticker=ticker,
                    break_type=BreakType.QUANTITY_MISMATCH,
                    our_quantity=our_qty,
                    counterparty_quantity=cpty_qty,
                )
            )

    for ticker, cpty_qty in cpty_by_ticker.items():
        if ticker not in our_by_ticker:
            breaks.append(
                BreakItem(
                    ticker=ticker,
                    break_type=BreakType.EXTRA_IN_COUNTERPARTY_VIEW,
                    our_quantity=None,
                    counterparty_quantity=cpty_qty,
                )
            )

    return breaks


def reconcile(
    our_positions: list[Position],
    counterparty_positions: list[Position],
    our_total: float,
    counterparty_total: float,
    tolerance: float,
) -> ReconciliationResult:
    """Reconciliation gate (AGENTS.md's "if they diverge beyond tolerance"):
    a total-amount mismatch within tolerance is treated as agreed even if
    individual trades differ (e.g. offsetting breaks) -- break_items are
    only computed (isolated) once a genuine, material disagreement exists,
    matching the Reconciliation Agent's literal Outputs contract."""
    agreed = abs(our_total - counterparty_total) <= tolerance
    break_items = [] if agreed else diff_trades(our_positions, counterparty_positions)
    return ReconciliationResult(agreed=agreed, break_items=break_items)
