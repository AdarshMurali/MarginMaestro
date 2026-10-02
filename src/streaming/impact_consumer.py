"""Impact consumer (MM-121): turns an `ImpactSet` from `market.impact` into
margin-call runs -- one orchestrator run per affected counterparty, the same
`start_run` that `/simulate` uses. Until now nothing consumed `market.impact`,
so a real price shock never started a run.

Exactly once per (event, counterparty): before a run starts, a claim row
`run:<thread_id>` is inserted into `processed_events` (primary key, so a
redelivered or concurrent duplicate fails the insert and is skipped).

- Known business outcomes (missing CSA terms, pricing gaps, market data down,
  a guardrail block) are logged and kept claimed -- retrying them would only
  repeat the same LLM calls.
- Anything unexpected releases the claim and re-raises, so the message is
  redelivered and the run tried again.

Runs pause at the approval gate (human in the loop), so a successful run here
never sends anything to a client by itself.
"""

from collections.abc import Callable
from datetime import UTC, datetime

import structlog
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from agents.csa_rag import CSATermsUnavailableError
from agents.orchestrator import MarginCallState, start_run, thread_id_for
from calc.models import PricingError
from persistence.db.models import ProcessedEventORM
from ports.guardrail import GuardrailError
from streaming.market_feed import MarketDataUnavailableError
from streaming.schemas import ImpactSet

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


def handle_impact(
    impact: ImpactSet,
    session_factory: sessionmaker[Session],
    graph_factory: Callable[[], CompiledStateGraph],
) -> list[str]:
    """Starts a run for each affected counterparty not already claimed;
    returns the thread ids started."""
    started: list[str] = []
    graph: CompiledStateGraph | None = None
    for counterparty_id in impact.counterparty_ids:
        thread_id = thread_id_for(impact, counterparty_id)
        log = logger.bind(correlation_id=impact.event_id, thread_id=thread_id)
        if not claim_run(session_factory, thread_id):
            log.info("impact_run_already_claimed")
            continue
        graph = graph or graph_factory()
        state = MarginCallState(
            correlation_id=impact.event_id, impact=impact, counterparty_id=counterparty_id
        )
        try:
            start_run(graph, state)
        except HANDLED_RUN_ERRORS as exc:
            log.warning("impact_run_held", error_type=type(exc).__name__, error=str(exc))
            continue
        except Exception:
            release_run(session_factory, thread_id)
            raise
        started.append(thread_id)
    return started
