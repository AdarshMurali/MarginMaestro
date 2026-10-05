"""Checkpoint allow-list (found 2026-10-05: LangGraph will block
unregistered types, which would make every saved margin call unreadable)."""

import enum
from datetime import UTC, datetime

from pydantic import BaseModel

from agents.orchestrator import MarginCallState
from agents.state_serde import allowed_modules, checkpoint_serializer, reachable_types
from calc.models import BreachResult
from streaming.schemas import MarketEventType


class _Colour(enum.Enum):
    RED = "red"


class _Leaf(BaseModel):
    colour: _Colour


class _Root(BaseModel):
    leaves: list[_Leaf] | None = None
    by_name: dict[str, _Leaf] = {}
    when: datetime | None = None


def test_walks_unions_lists_and_dicts():
    assert reachable_types(_Root) == {_Root, _Leaf, _Colour}


def test_every_state_type_is_allowed():
    allowed = set(allowed_modules(MarginCallState))

    assert ("calc.models", "BreachResult") in allowed
    assert ("streaming.schemas", "MarketEventType") in allowed
    assert ("agents.orchestrator", "MarginCallState") in allowed


def test_a_state_value_round_trips_under_the_allow_list():
    serde = checkpoint_serializer(MarginCallState)
    value = {
        "breach": BreachResult(breached=True, call_amount=61871.37),
        "kind": MarketEventType.PRICE_SHOCK,
        "at": datetime(2026, 10, 5, tzinfo=UTC),
    }

    loaded = serde.loads_typed(serde.dumps_typed(value))

    assert loaded == value
    assert isinstance(loaded["breach"], BreachResult)
