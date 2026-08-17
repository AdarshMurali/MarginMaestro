from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

import structlog
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from agents.communication import NotificationResult, draft_margin_call_notice, send_slack_notice
from agents.csa_rag import answer_csa_terms
from agents.escalation import (
    IncidentResult,
    open_servicenow_incident,
    retrieve_escalation_procedure,
)
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
from persistence.db.checkpoint_saver import AzureSQLSaver
from persistence.db.engine import get_session_factory
from persistence.db.models import (
    CollateralItemORM,
    PortfolioORM,
    PositionORM,
    RatingORM,
    ReferenceRateORM,
)
from persistence.models import AssetClass, Position, RatingGrade
from streaming.event_agent import latest_close_before
from streaming.market_feed import MarketFeed, get_market_feed
from streaming.schemas import ImpactSet

logger = structlog.get_logger()


class MarginCallState(BaseModel):
    """One graph run per (ImpactSet, counterparty_id) pair -- an ImpactSet
    naming several counterparties fans out into separate runs, not one run
    juggling all of them. Run identity is thread_id_for(impact,
    counterparty_id); see get_or_start_run() for idempotent dispatch."""

    correlation_id: str = Field(default_factory=lambda: uuid4().hex)
    impact: ImpactSet
    counterparty_id: str

    portfolio_mtm: PortfolioMTM | None = None
    variation_margin: VariationMargin | None = None
    initial_margin: InitialMargin | None = None
    csa_terms: CSATerms | None = None
    breach_result: BreachResult | None = None
    approval_decision: Literal["approved", "rejected", "adjusted"] | None = None
    adjusted_call_amount: float | None = None
    notification_result: NotificationResult | None = None
    notification_sent_at: datetime | None = None
    sla_outcome: Literal["met", "breached"] | None = None
    escalation_result: IncidentResult | None = None


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
        "csa_terms": CSATerms(
            threshold=result.threshold,
            mta=result.mta,
            currency=result.currency,
            rating_triggers=result.rating_triggers,
        )
    }


def _current_rating(session: Session, counterparty_id: str) -> RatingGrade | None:
    grade = session.execute(
        select(RatingORM.grade)
        .where(RatingORM.counterparty_id == counterparty_id)
        .order_by(RatingORM.rating_date.desc())
        .limit(1)
    ).scalar_one_or_none()
    return RatingGrade(grade) if grade is not None else None


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
    current_rating = _current_rating(session, state.counterparty_id)
    result = evaluate_breach(exposure, collateral_held, state.csa_terms, current_rating)
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
    # Logged only here, not before interrupt(): LangGraph replays this whole
    # node function from the top on resume, so anything before interrupt()
    # would double-log (once on the pausing call, once per resume).
    logger.bind(correlation_id=state.correlation_id, counterparty_id=state.counterparty_id).info(
        "await_approval_resumed", decision=decision
    )
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


def _effective_call_amount(state: MarginCallState) -> float:
    """The amount actually communicated to the counterparty: the adjusted
    figure when the approval decision adjusted it, else the computed breach
    amount. Shared by send_notification and escalate so both always agree
    on what was actually called for."""
    assert state.breach_result is not None  # callers already guard this
    if state.approval_decision == "adjusted" and state.adjusted_call_amount is not None:
        return state.adjusted_call_amount
    return state.breach_result.call_amount


def send_notification(state: MarginCallState, settings: Settings) -> dict:
    """Communication Agent (MM-41, docs/AGENTS.md #6): only reached after
    await_approval when the decision is "approved"/"adjusted" -- routing
    (_route_after_approval) keeps "rejected" from ever calling this, matching
    AGENTS.md's "never sends before/without approval" note."""
    if state.breach_result is None or state.csa_terms is None:
        raise PricingError(
            "send_notification requires breach_result and csa_terms to already be set on state"
        )

    call_amount = _effective_call_amount(state)
    notice_text = draft_margin_call_notice(
        state.counterparty_id,
        call_amount,
        state.csa_terms.currency,
        state.csa_terms,
        settings=settings,
    )
    result = send_slack_notice(notice_text, settings=settings)
    return {"notification_result": result, "notification_sent_at": datetime.now(UTC)}


def await_sla_response(state: MarginCallState, settings: Settings) -> dict:
    """SLA timer (MM-42, docs/AGENTS.md "SLA & Escalation"): pauses
    (interrupt()) after notification, resolving "met" if a response signal
    arrives before the deadline, or "breached" once the deadline has passed.
    No real counterparty-facing channel exists in this demo, so "responded"
    is a provisional signal -- see the /respond endpoint's note in
    docs/ROADMAP.md. Resuming with neither signal (a periodic external check,
    not yet a real scheduler) just re-pauses if the deadline hasn't passed."""
    if state.notification_sent_at is None:
        raise PricingError("await_sla_response requires notification_sent_at to already be set")

    deadline = state.notification_sent_at + timedelta(minutes=settings.margin_call_sla_minutes)
    log = logger.bind(correlation_id=state.correlation_id, counterparty_id=state.counterparty_id)
    while True:
        payload = {
            "correlation_id": state.correlation_id,
            "counterparty_id": state.counterparty_id,
            "deadline": deadline.isoformat(),
        }
        # A resume payload must be non-empty: LangGraph's Command(resume=...)
        # does not correctly resolve an interrupt() call when given `{}` --
        # confirmed by a direct repro before relying on this pattern.
        resume = interrupt(payload)
        if resume.get("responded"):
            log.info("sla_met")
            return {"sla_outcome": "met"}
        if datetime.now(UTC) >= deadline:
            log.info("sla_breached", deadline=deadline.isoformat())
            return {"sla_outcome": "breached"}


def escalate(state: MarginCallState, settings: Settings) -> dict:
    """SLA & Escalation (MM-43, docs/AGENTS.md "SLA & Escalation"): only
    reached when the SLA was breached (_route_after_sla) -- retrieves the
    escalation-procedures document (RAG) and opens a ServiceNow incident
    with full run context (docs/adr/0007)."""
    if state.breach_result is None or state.csa_terms is None or state.notification_sent_at is None:
        raise PricingError(
            "escalate requires breach_result, csa_terms, and notification_sent_at to already "
            "be set on state"
        )

    deadline = state.notification_sent_at + timedelta(minutes=settings.margin_call_sla_minutes)
    procedure_excerpt = retrieve_escalation_procedure(settings=settings)
    result = open_servicenow_incident(
        state.correlation_id,
        state.counterparty_id,
        _effective_call_amount(state),
        state.csa_terms.currency,
        state.csa_terms.threshold,
        state.notification_sent_at,
        deadline,
        procedure_excerpt,
        settings=settings,
    )
    return {"escalation_result": result}


def _route_after_breach(state: MarginCallState) -> str:
    if state.breach_result is not None and state.breach_result.breached:
        return "await_approval"
    return END


def _route_after_sla(state: MarginCallState) -> str:
    if state.sla_outcome == "breached":
        return "escalate"
    return END


def _route_after_approval(state: MarginCallState) -> str:
    if state.approval_decision in ("approved", "adjusted"):
        return "send_notification"
    return END


def thread_id_for(impact: ImpactSet, counterparty_id: str) -> str:
    """The checkpointer's run key. Matches MM-38's planned event_id +
    counterparty_id idempotency key -- adopted early here since interrupt()/
    resume needs a stable thread_id regardless."""
    return f"{impact.event_id}:{counterparty_id}"


def start_run(graph: CompiledStateGraph, state: MarginCallState) -> dict:
    thread_id = thread_id_for(state.impact, state.counterparty_id)
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    log = logger.bind(
        correlation_id=state.correlation_id,
        thread_id=thread_id,
        counterparty_id=state.counterparty_id,
    )
    log.info("orchestrator_run_started", event_id=state.impact.event_id)
    result = graph.invoke(state, config=config)
    log.info(
        (
            "orchestrator_run_paused_for_approval"
            if "__interrupt__" in result
            else "orchestrator_run_ended"
        ),
    )
    return result


def resume_run(graph: CompiledStateGraph, thread_id: str, resume_payload: dict) -> dict:
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    log = logger.bind(thread_id=thread_id)
    log.info("orchestrator_run_resume_requested", decision=resume_payload.get("decision"))
    result = graph.invoke(Command(resume=resume_payload), config=config)
    log.info("orchestrator_run_ended", approval_decision=result.get("approval_decision"))
    return result


def get_or_start_run(graph: CompiledStateGraph, state: MarginCallState) -> dict:
    """Idempotent entry point: replaying the same (event_id, counterparty_id)
    must not double-raise a margin call (CLAUDE.md's idempotency rule). If a
    run already exists for this thread_id -- still paused or already
    finished -- returns its current state instead of invoking the graph
    again."""
    thread_id = thread_id_for(state.impact, state.counterparty_id)
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    snapshot = graph.get_state(config)
    if snapshot.values:
        logger.bind(correlation_id=state.correlation_id, thread_id=thread_id).info(
            "orchestrator_run_already_exists"
        )
        result = dict(snapshot.values)
        if snapshot.interrupts:
            result["__interrupt__"] = list(snapshot.interrupts)
        return result
    return start_run(graph, state)


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

    checkpointer defaults to AzureSQLSaver (MM-38) -- persisted to this
    project's own SQL database, so a paused run survives a process restart.
    Still overridable (e.g. InMemorySaver in tests that don't care about
    restart survival)."""
    settings = settings or get_settings()
    session_factory = session_factory or get_session_factory(settings)
    market_feed = market_feed or get_market_feed(settings)
    checkpointer = checkpointer or AzureSQLSaver(session_factory)

    def _compute_exposure_node(state: MarginCallState) -> dict:
        log = logger.bind(
            correlation_id=state.correlation_id, counterparty_id=state.counterparty_id
        )
        with session_factory() as session:
            result = compute_exposure(state, session, market_feed)
        log.info(
            "compute_exposure_completed",
            variation_margin=result["variation_margin"].variation_margin,
            initial_margin=result["initial_margin"].initial_margin,
        )
        return result

    def _fetch_csa_terms_node(state: MarginCallState) -> dict:
        log = logger.bind(
            correlation_id=state.correlation_id, counterparty_id=state.counterparty_id
        )
        result = fetch_csa_terms(state, settings)
        log.info("fetch_csa_terms_completed", threshold=result["csa_terms"].threshold)
        return result

    def _evaluate_breach_node(state: MarginCallState) -> dict:
        log = logger.bind(
            correlation_id=state.correlation_id, counterparty_id=state.counterparty_id
        )
        with session_factory() as session:
            result = evaluate_breach_node(state, session)
        log.info(
            "evaluate_breach_completed",
            breached=result["breach_result"].breached,
            call_amount=result["breach_result"].call_amount,
        )
        return result

    def _send_notification_node(state: MarginCallState) -> dict:
        log = logger.bind(
            correlation_id=state.correlation_id, counterparty_id=state.counterparty_id
        )
        result = send_notification(state, settings)
        log.info(
            "send_notification_completed",
            slack_channel=result["notification_result"].slack_channel,
        )
        return result

    def _await_sla_response_node(state: MarginCallState) -> dict:
        return await_sla_response(state, settings)

    def _escalate_node(state: MarginCallState) -> dict:
        log = logger.bind(
            correlation_id=state.correlation_id, counterparty_id=state.counterparty_id
        )
        result = escalate(state, settings)
        log.info(
            "escalate_completed",
            incident_number=result["escalation_result"].incident_number,
        )
        return result

    graph = StateGraph(MarginCallState)
    graph.add_node("compute_exposure", _compute_exposure_node)
    graph.add_node("fetch_csa_terms", _fetch_csa_terms_node)
    graph.add_node("evaluate_breach", _evaluate_breach_node)
    graph.add_node("await_approval", await_approval)
    graph.add_node("send_notification", _send_notification_node)
    graph.add_node("await_sla_response", _await_sla_response_node)
    graph.add_node("escalate", _escalate_node)

    graph.add_edge(START, "compute_exposure")
    graph.add_edge("compute_exposure", "fetch_csa_terms")
    graph.add_edge("fetch_csa_terms", "evaluate_breach")
    graph.add_conditional_edges(
        "evaluate_breach", _route_after_breach, {"await_approval": "await_approval", END: END}
    )
    graph.add_conditional_edges(
        "await_approval",
        _route_after_approval,
        {"send_notification": "send_notification", END: END},
    )
    graph.add_edge("send_notification", "await_sla_response")
    graph.add_conditional_edges(
        "await_sla_response", _route_after_sla, {"escalate": "escalate", END: END}
    )
    graph.add_edge("escalate", END)

    return graph.compile(checkpointer=checkpointer)
