from typing import Literal

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel

from calc.models import BreachResult, CSATerms, InitialMargin, PortfolioMTM, VariationMargin
from streaming.schemas import ImpactSet


class MarginCallState(BaseModel):
    """One graph run per (ImpactSet, counterparty_id) pair -- an ImpactSet
    naming several counterparties fans out into separate runs, not one run
    juggling all of them. Run identity/idempotency keying lands in MM-38."""

    correlation_id: str
    impact: ImpactSet
    counterparty_id: str

    portfolio_mtm: PortfolioMTM | None = None
    variation_margin: VariationMargin | None = None
    initial_margin: InitialMargin | None = None
    csa_terms: CSATerms | None = None
    breach_result: BreachResult | None = None
    approval_decision: Literal["approved", "rejected", "adjusted"] | None = None


def compute_exposure(state: MarginCallState) -> dict:
    """Placeholder -- real compute_mtm/compute_variation_margin/
    compute_initial_margin wiring lands in MM-36."""
    return {}


def fetch_csa_terms(state: MarginCallState) -> dict:
    """Placeholder -- real agents.csa_rag.answer_csa_terms call lands in MM-36."""
    return {}


def evaluate_breach_node(state: MarginCallState) -> dict:
    """Placeholder -- real calc.breach.evaluate_breach call, plus the
    conditional edge that branches on BreachResult.breached, lands in MM-36."""
    return {}


def await_approval(state: MarginCallState) -> dict:
    """Placeholder -- real interrupt()/Command(resume=...) gate lands in MM-37."""
    return {}


def build_orchestrator_graph() -> CompiledStateGraph:
    """Skeleton wiring only: a linear chain through every node. MM-36 replaces
    the evaluate_breach -> await_approval edge with a conditional one (breach
    vs no-breach) once evaluate_breach_node has something to branch on."""
    graph = StateGraph(MarginCallState)
    graph.add_node("compute_exposure", compute_exposure)
    graph.add_node("fetch_csa_terms", fetch_csa_terms)
    graph.add_node("evaluate_breach", evaluate_breach_node)
    graph.add_node("await_approval", await_approval)

    graph.add_edge(START, "compute_exposure")
    graph.add_edge("compute_exposure", "fetch_csa_terms")
    graph.add_edge("fetch_csa_terms", "evaluate_breach")
    graph.add_edge("evaluate_breach", "await_approval")
    graph.add_edge("await_approval", END)

    return graph.compile()
