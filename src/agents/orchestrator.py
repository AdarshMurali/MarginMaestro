from datetime import UTC, datetime
from typing import Literal

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, interrupt
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from agents.csa_rag import answer_csa_terms
from calc.breach import evaluate_breach
from calc.im import compute_initial_margin
from calc.models import (
    BreachResult,
    CSATerms,
    InitialMargin,
    PortfolioMTM,
    PricingError,
    VariationMargin,
)
from calc.mtm import compute_mtm
from calc.vm import compute_variation_margin
from config.settings import Settings, get_settings
from persistence.db.engine import get_session_factory
from persistence.db.models import CollateralItemORM, PortfolioORM, PositionORM, ReferenceRateORM
from persistence.models import AssetClass, Position
from streaming.event_agent import latest_close_before
from streaming.market_feed import MarketFeed, get_market_feed
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
    adjusted_call_amount: float | None = None


def _load_positions(session: Session, counterparty_id: str) -> list[Position]:
    """Relies on the data model's one-portfolio-per-counterparty invariant
    (Phase 1/MM-11) -- compute_mtm() requires every position to share one
    portfolio_id."""
    rows = (
        session.execute(
            select(PositionORM)
            .join(PortfolioORM, PositionORM.portfolio_id == PortfolioORM.id)
            .where(PortfolioORM.counterparty_id == counterparty_id)
        )
        .scalars()
        .all()
    )
    return [
        Position(
            id=row.id,
            portfolio_id=row.portfolio_id,
            ticker=row.ticker,
            asset_class=AssetClass(row.asset_class),
            quantity=row.quantity,
            trade_date=row.trade_date,
        )
        for row in rows
    ]


def _latest_vix(session: Session) -> float:
    value = session.execute(
        select(ReferenceRateORM.value)
        .where(ReferenceRateORM.series_id == "VIXCLS")
        .order_by(ReferenceRateORM.rate_date.desc())
        .limit(1)
    ).scalar_one_or_none()
    if value is None:
        raise PricingError("No VIXCLS reference rate available to compute Initial Margin")
    return value


def _collateral_held(session: Session, counterparty_id: str) -> float:
    rows = session.execute(
        select(CollateralItemORM.value_usd, CollateralItemORM.haircut_pct).where(
            CollateralItemORM.counterparty_id == counterparty_id
        )
    ).all()
    return sum(value_usd * (1 - haircut_pct) for value_usd, haircut_pct in rows)


def compute_exposure(state: MarginCallState, session: Session, market_feed: MarketFeed) -> dict:
    positions = _load_positions(session, state.counterparty_id)
    if not positions:
        raise PricingError(f"No positions found for counterparty {state.counterparty_id}")

    tickers = sorted({p.ticker for p in positions})
    now = datetime.now(UTC)

    current_prices = {t: q.price for t, q in market_feed.get_prices(tickers).items()}
    prior_prices = {
        t: close for t in tickers if (close := latest_close_before(session, t, now)) is not None
    }

    mtm_today = compute_mtm(positions, current_prices)
    mtm_prior = compute_mtm(positions, prior_prices)
    variation_margin = compute_variation_margin(mtm_today, mtm_prior)
    initial_margin = compute_initial_margin(mtm_today, _latest_vix(session))

    return {
        "portfolio_mtm": mtm_today,
        "variation_margin": variation_margin,
        "initial_margin": initial_margin,
    }


def fetch_csa_terms(state: MarginCallState, settings: Settings) -> dict:
    result = answer_csa_terms(state.counterparty_id, settings=settings)
    return {
        "csa_terms": CSATerms(threshold=result.threshold, mta=result.mta, currency=result.currency)
    }


def evaluate_breach_node(state: MarginCallState, session: Session) -> dict:
    if state.variation_margin is None or state.initial_margin is None or state.csa_terms is None:
        raise PricingError(
            "evaluate_breach requires variation_margin, initial_margin, and csa_terms "
            "to already be set on state -- compute_exposure/fetch_csa_terms must run first"
        )

    # Standard bilateral-CSA exposure: MTM swing since last exchange (VM) plus
    # the independent IM add-on. "Directionally correct" per CLAUDE.md golden
    # rule 1, not a certified risk model.
    exposure = state.variation_margin.variation_margin + state.initial_margin.initial_margin
    collateral_held = _collateral_held(session, state.counterparty_id)
    result = evaluate_breach(exposure, collateral_held, state.csa_terms)
    return {"breach_result": result}


def await_approval(state: MarginCallState) -> dict:
    """Pauses the graph (LangGraph interrupt()) carrying the proposed call
    amount, resuming on Command(resume={"decision": ..., "adjusted_call_amount":
    ...}). "decision" must be one of MarginCallState.approval_decision's
    literals; "adjusted_call_amount" only matters when decision == "adjusted".
    Provisional endpoint -- see MM-37 note in docs/ROADMAP.md."""
    if state.breach_result is None:
        raise PricingError("await_approval requires breach_result to already be set")

    payload = {
        "correlation_id": state.correlation_id,
        "counterparty_id": state.counterparty_id,
        "call_amount": state.breach_result.call_amount,
        "currency": state.csa_terms.currency if state.csa_terms else "USD",
    }
    resume = interrupt(payload)

    decision = resume["decision"]
    return {
        "approval_decision": decision,
        # Explicit key even when None: LangGraph's Pydantic-schema state only
        # returns channels that were actually written at least once (exclude_unset
        # semantics) -- omitting this key on non-"adjusted" decisions would leave
        # it missing from invoke()'s result dict entirely, not just None.
        "adjusted_call_amount": (
            resume.get("adjusted_call_amount") if decision == "adjusted" else None
        ),
    }


def _route_after_breach(state: MarginCallState) -> str:
    if state.breach_result is not None and state.breach_result.breached:
        return "await_approval"
    return END


def thread_id_for(impact: ImpactSet, counterparty_id: str) -> str:
    """The checkpointer's run key. Matches MM-38's planned event_id +
    counterparty_id idempotency key -- adopted early here since interrupt()/
    resume needs a stable thread_id regardless."""
    return f"{impact.event_id}:{counterparty_id}"


def start_run(graph: CompiledStateGraph, state: MarginCallState) -> dict:
    config: RunnableConfig = {
        "configurable": {"thread_id": thread_id_for(state.impact, state.counterparty_id)}
    }
    return graph.invoke(state, config=config)


def resume_run(graph: CompiledStateGraph, thread_id: str, resume_payload: dict) -> dict:
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    return graph.invoke(Command(resume=resume_payload), config=config)


def build_orchestrator_graph(
    session_factory: sessionmaker[Session] | None = None,
    market_feed: MarketFeed | None = None,
    settings: Settings | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Each DB-touching node opens its own short-lived session (matching
    persistence.batch_loader's convention) rather than holding one open across
    the whole run -- await_approval can pause for a long time (up to
    MARGIN_CALL_SLA_MINUTES), and a session shouldn't sit open through that.

    checkpointer defaults to an in-memory one -- MM-38 swaps in a persisted
    (Azure SQL) one so a paused run survives a process restart; in-memory is
    enough for interrupt()/resume to work within a single process for now."""
    settings = settings or get_settings()
    session_factory = session_factory or get_session_factory(settings)
    market_feed = market_feed or get_market_feed(settings)
    checkpointer = checkpointer or InMemorySaver()

    def _compute_exposure_node(state: MarginCallState) -> dict:
        with session_factory() as session:
            return compute_exposure(state, session, market_feed)

    def _fetch_csa_terms_node(state: MarginCallState) -> dict:
        return fetch_csa_terms(state, settings)

    def _evaluate_breach_node(state: MarginCallState) -> dict:
        with session_factory() as session:
            return evaluate_breach_node(state, session)

    graph = StateGraph(MarginCallState)
    graph.add_node("compute_exposure", _compute_exposure_node)
    graph.add_node("fetch_csa_terms", _fetch_csa_terms_node)
    graph.add_node("evaluate_breach", _evaluate_breach_node)
    graph.add_node("await_approval", await_approval)

    graph.add_edge(START, "compute_exposure")
    graph.add_edge("compute_exposure", "fetch_csa_terms")
    graph.add_edge("fetch_csa_terms", "evaluate_breach")
    graph.add_conditional_edges(
        "evaluate_breach", _route_after_breach, {"await_approval": "await_approval", END: END}
    )
    graph.add_edge("await_approval", END)

    return graph.compile(checkpointer=checkpointer)
