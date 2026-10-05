"""Impact consumer (MM-121): turns an `ImpactSet` from `market.impact` into
margin-call runs -- one dispatch per affected counterparty. Until MM-121
nothing consumed `market.impact`, so a real price shock never started a run.

MM-125: each counterparty goes through the margin-call policy
(agents.margin_policy.dispatch_trigger) instead of always starting a run: the
intraday materiality gate, and one open call per counterparty. The daily
margin run (`daily_margin_run_impact`) is an impact set too and takes the same
path.

Exactly once per (event, counterparty): before dispatching, a claim row
`run:<thread_id>` is inserted into `processed_events` (primary key, so a
redelivered or concurrent duplicate fails the insert and is skipped).

- Known business outcomes (missing CSA terms, pricing gaps, market data down,
  a guardrail block) are logged and kept claimed -- retrying them would only
  repeat the same LLM calls.
- A counterparty busy with another trigger releases its claim; once every
  other counterparty is done, CounterpartyBusyError is raised so the message
  is redelivered (Pub/Sub) or the job retried (Cloud Scheduler).
- Anything unexpected releases the claim and re-raises, so the message is
  redelivered and the run tried again.

Runs pause at the approval gate (human in the loop), so a successful run here
never sends anything to a client by itself.
"""

from collections.abc import Callable
from datetime import UTC, date, datetime

import structlog
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from agents.csa_rag import CSATermsUnavailableError
from agents.margin_policy import CounterpartyBusyError, TriggerOutcome, dispatch_trigger
from agents.orchestrator import thread_id_for
from calc.models import PricingError
from persistence.db.models import PortfolioORM, ProcessedEventORM
from ports.guardrail import GuardrailError
from streaming.market_feed import MarketDataUnavailableError
from streaming.schemas import ImpactSet, MarketEventType

logger = structlog.get_logger()

HANDLED_RUN_ERRORS = (
    PricingError,
    CSATermsUnavailableError,
    MarketDataUnavailableError,
    GuardrailError,
)


def run_claim_id(thread_id: str) -> str:
    return f"run:{thread_id}"


def claim_run(session_factory: sessionmaker[Session], thread_id: str) -> bool:
    """True if this caller now owns the run; False if it was already claimed."""
    with session_factory() as session:
        session.add(
            ProcessedEventORM(event_id=run_claim_id(thread_id), processed_at=datetime.now(UTC))
        )
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            return False
    return True


def release_run(session_factory: sessionmaker[Session], thread_id: str) -> None:
    with session_factory() as session:
        session.execute(
            delete(ProcessedEventORM).where(ProcessedEventORM.event_id == run_claim_id(thread_id))
        )
        session.commit()


def daily_margin_run_impact(session: Session, run_date: date) -> ImpactSet:
    """The daily margin run (MM-125) as an impact set naming every
    counterparty with a book. One id per day, so a retried or repeated run
    on the same day is a no-op per counterparty (the claim above). The date
    is the UTC date: the job runs at 16:45 New York, the same calendar day
    in UTC."""
    counterparty_ids = sorted(
        session.execute(select(PortfolioORM.counterparty_id).distinct()).scalars()
    )
    return ImpactSet(
        event_id=f"daily-margin-run:{run_date.isoformat()}",
        event_type=MarketEventType.DAILY_MARGIN_RUN,
        counterparty_ids=counterparty_ids,
        reason=f"Daily margin run for {run_date.isoformat()}",
        occurred_at=datetime.now(UTC),
    )


def handle_impact(
    impact: ImpactSet,
    session_factory: sessionmaker[Session],
    graph_factory: Callable[[], CompiledStateGraph],
) -> list[TriggerOutcome]:
    """Dispatches each affected counterparty not already claimed; returns
    what happened to each one dispatched (started, updated or unchanged)."""
    outcomes: list[TriggerOutcome] = []
    busy: list[str] = []
    graph: CompiledStateGraph | None = None
    for counterparty_id in impact.counterparty_ids:
        thread_id = thread_id_for(impact, counterparty_id)
        log = logger.bind(correlation_id=impact.event_id, thread_id=thread_id)
        if not claim_run(session_factory, thread_id):
            log.info("impact_run_already_claimed")
            continue
        graph = graph or graph_factory()
        try:
            outcome = dispatch_trigger(graph, impact, counterparty_id, session_factory)
        except HANDLED_RUN_ERRORS as exc:
            log.warning("impact_run_held", error_type=type(exc).__name__, error=str(exc))
            continue
        except CounterpartyBusyError:
            log.info("impact_run_counterparty_busy")
            release_run(session_factory, thread_id)
            busy.append(counterparty_id)
            continue
        except Exception:
            release_run(session_factory, thread_id)
            raise
        log.info("impact_run_dispatched", action=outcome.action.value)
        outcomes.append(outcome)
    if busy:
        raise CounterpartyBusyError(f"Retry for busy counterparties: {', '.join(busy)}")
    return outcomes
