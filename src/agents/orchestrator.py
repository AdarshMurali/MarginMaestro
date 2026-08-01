from datetime import UTC, datetime
from typing import Literal

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
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
    """Placeholder -- real interrupt()/Command(resume=...) gate lands in MM-37."""
    return {}


def _route_after_breach(state: MarginCallState) -> str:
    if state.breach_result is not None and state.breach_result.breached:
        return "await_approval"
    return END


def build_orchestrator_graph(
    session_factory: sessionmaker[Session] | None = None,
    market_feed: MarketFeed | None = None,
    settings: Settings | None = None,
) -> CompiledStateGraph:
    """Each DB-touching node opens its own short-lived session (matching
    persistence.batch_loader's convention) rather than holding one open across
    the whole run -- await_approval can pause for a long time (up to
    MARGIN_CALL_SLA_MINUTES), and a session shouldn't sit open through that."""
    settings = settings or get_settings()
    session_factory = session_factory or get_session_factory(settings)
    market_feed = market_feed or get_market_feed(settings)

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

    return graph.compile()
