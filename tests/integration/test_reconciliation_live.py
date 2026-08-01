"""Real RAG retrieval + real OpenAI calls. Excluded from the default/CI test
run (see the `live` marker in pyproject.toml).

Run explicitly with: pytest -m live tests/integration/test_reconciliation_live.py
"""

from datetime import date

import pytest

from agents.reconciliation import reconcile_call
from calc.trade_diff import BreakType
from persistence.models import AssetClass, Position

pytestmark = pytest.mark.live


def _position(id_: str, ticker: str, quantity: float) -> Position:
    return Position(
        id=id_,
        portfolio_id="PF-1",
        ticker=ticker,
        asset_class=AssetClass.EQUITY,
        quantity=quantity,
        trade_date=date(2026, 1, 1),
    )


def test_disagreed_break_retrieves_real_precedent_and_drafts_a_grounded_resolution() -> None:
    our = [_position("POS-1", "AAPL", 100.0)]
    counterparty = [_position("POS-1", "AAPL", 80.0)]  # genuine quantity mismatch

    result = reconcile_call(
        our,
        counterparty,
        our_total=1_000_000.0,
        counterparty_total=900_000.0,  # beyond tolerance -> triggers a real RAG+LLM draft
        tolerance=1_000.0,
    )

    assert result.agreed is False
    assert len(result.break_items) == 1
    assert result.break_items[0].break_type == BreakType.QUANTITY_MISMATCH
    assert result.suggested_resolution
    assert result.citations
    assert any(c.source_file.startswith("exceptions/") for c in result.citations)


def test_agreed_within_tolerance_returns_no_resolution() -> None:
    our = [_position("POS-1", "AAPL", 100.0)]
    counterparty = [_position("POS-1", "AAPL", 100.0)]

    result = reconcile_call(
        our, counterparty, our_total=1_000_000.0, counterparty_total=1_000_050.0, tolerance=1_000.0
    )

    assert result.agreed is True
    assert result.suggested_resolution is None
    assert result.break_items == []
