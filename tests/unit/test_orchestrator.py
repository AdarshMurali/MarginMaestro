from datetime import UTC, datetime

from agents.orchestrator import MarginCallState, build_orchestrator_graph
from streaming.schemas import ImpactSet, MarketEventType


def _state() -> MarginCallState:
    impact = ImpactSet(
        event_id="evt-1",
        event_type=MarketEventType.PRICE_SHOCK,
        counterparty_ids=["CP-1"],
        reason="TSLA moved 12.0% vs prior close",
        occurred_at=datetime.now(UTC),
    )
    return MarginCallState(correlation_id="corr-1", impact=impact, counterparty_id="CP-1")


class TestMarginCallState:
    def test_defaults_are_unset(self) -> None:
        state = _state()

        assert state.portfolio_mtm is None
        assert state.variation_margin is None
        assert state.initial_margin is None
        assert state.csa_terms is None
        assert state.breach_result is None
        assert state.approval_decision is None


class TestBuildOrchestratorGraph:
    def test_compiles(self) -> None:
        assert build_orchestrator_graph() is not None

    def test_runs_end_to_end_through_every_skeleton_node(self) -> None:
        graph = build_orchestrator_graph()

        result = graph.invoke(_state())

        assert result["correlation_id"] == "corr-1"
        assert result["counterparty_id"] == "CP-1"
        assert result["impact"].event_id == "evt-1"
        assert result.get("breach_result") is None
