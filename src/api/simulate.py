"""Simulate Event panel (MM-56): triggers the real orchestrator lifecycle
directly, for demo/manual use -- deliberately bypasses the Kafka/Event
Agent hop (MM-31/32) that's the real ingestion path for genuine live market
ticks, the same way the approve/respond endpoints already resume the
orchestrator directly rather than round-tripping through Kafka. Applies a
user-chosen ticker/%% delta on top of a real baseline price (the same
streaming.simulator.SimulatedMarketFeed class `make simulate` publishes to
Kafka with, just built from a one-off PriceScenario instead of a canned one)
and reuses the same affected_counterparties() lookup the real Event Agent
uses, so a click here evaluates exactly the real counterparties a genuine
matching market event would."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from agents.csa_rag import CSATermsUnavailableError
from agents.orchestrator import MarginCallState, build_orchestrator_graph, start_run, thread_id_for
from api.schemas import SimulatedCounterpartyResult, SimulateEventResponse
from calc.models import PricingError
from config.settings import Settings
from streaming.event_agent import affected_counterparties
from streaming.market_feed import CompositeMarketFeed, MarketDataUnavailableError, MarketFeed
from streaming.schemas import ImpactSet, MarketEventType
from streaming.simulator import PriceScenario, SimulatedMarketFeed


def trigger_simulation(
    event_type: MarketEventType,
    ticker: str,
    pct_change: float,
    session: Session,
    session_factory: sessionmaker[Session],
    settings: Settings,
    base_feed: MarketFeed | None = None,
) -> SimulateEventResponse:
    """pct_change is a fraction (e.g. -0.125 for -12.5%%), not a percent --
    the /simulate endpoint converts the request's percent input before
    calling this."""
    counterparty_ids = sorted(affected_counterparties(session, ticker))
    reason = f"Simulated {event_type.value}: {ticker} {pct_change:+.1%}"

    event_id = f"sim-{uuid4()}"
    impact = ImpactSet(
        event_id=event_id,
        event_type=event_type,
        counterparty_ids=counterparty_ids,
        reason=reason,
        occurred_at=datetime.now(UTC),
    )

    # A real baseline (never a second synthetic layer, even when this
    # project's own MARKET_FEED_MODE=simulated locally) shocked by the
    # user-chosen delta -- matches run_scenario()'s own convention for the
    # Kafka path. base_feed is injectable (same pattern as run_scenario
    # itself) so tests can avoid a real yfinance/CoinGecko call.
    price_scenario = PriceScenario(event_type=event_type, ticker_deltas={ticker: pct_change})
    shocked_feed = SimulatedMarketFeed(
        price_scenario=price_scenario, base_feed=base_feed or CompositeMarketFeed()
    )
    graph = build_orchestrator_graph(
        session_factory=session_factory, market_feed=shocked_feed, settings=settings
    )

    results: list[SimulatedCounterpartyResult] = []
    for counterparty_id in counterparty_ids:
        state = MarginCallState(
            correlation_id=event_id, impact=impact, counterparty_id=counterparty_id
        )
        try:
            result = start_run(graph, state)
        except (PricingError, CSATermsUnavailableError, MarketDataUnavailableError) as exc:
            results.append(
                SimulatedCounterpartyResult(counterparty_id=counterparty_id, error=str(exc))
            )
            continue

        breach_result = result.get("breach_result")
        results.append(
            SimulatedCounterpartyResult(
                counterparty_id=counterparty_id,
                thread_id=thread_id_for(impact, counterparty_id),
                breached=breach_result.breached if breach_result is not None else None,
                call_amount=breach_result.call_amount if breach_result is not None else None,
            )
        )

    return SimulateEventResponse(
        event_type=event_type.value, reason=reason, affected_counterparties=results
    )
