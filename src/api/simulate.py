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
matching market event would.

MM-125: each counterparty goes through the same margin-call policy as a live
event (agents.margin_policy.dispatch_trigger) -- the intraday materiality
gate and one open call per counterparty -- so the demo shows what the live
path would do. The simulated move (baseline -> shocked price) travels on the
impact set, like a live shock's."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from agents.csa_rag import CSATermsUnavailableError
from agents.margin_policy import CounterpartyBusyError, dispatch_trigger
from agents.orchestrator import build_orchestrator_graph
from api.schemas import SimulatedCounterpartyResult, SimulateEventResponse
from calc.models import PriceMove, PricingError
from config.settings import Settings
from ports.guardrail import GuardrailError
from streaming.event_agent import affected_counterparties
from streaming.market_feed import CompositeMarketFeed, MarketDataUnavailableError, MarketFeed
from streaming.schemas import ImpactSet, MarketEventType
from streaming.simulator import PriceScenario, SimulatedMarketFeed


def _simulated_move(ticker: str, pct_change: float, base_feed: MarketFeed) -> list[PriceMove]:
    """The shock as a price move, from the same real baseline the shocked
    feed starts from. No baseline price (feed gap) -> no move: the gate then
    doesn't apply, and the run reports the pricing gap as before."""
    try:
        quote = base_feed.get_prices([ticker]).get(ticker)
    except MarketDataUnavailableError:
        return []  # each counterparty's run reports the outage itself
    if quote is None or quote.price <= 0 or pct_change <= -1:
        return []
    return [
        PriceMove(ticker=ticker, from_price=quote.price, to_price=quote.price * (1 + pct_change))
    ]


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
    # A real baseline (never a second synthetic layer, even when this
    # project's own MARKET_FEED_MODE=simulated locally) shocked by the
    # user-chosen delta -- matches run_scenario()'s own convention for the
    # Kafka path. base_feed is injectable (same pattern as run_scenario
    # itself) so tests can avoid a real yfinance/CoinGecko call.
    base_feed = base_feed or CompositeMarketFeed()

    event_id = f"sim-{uuid4()}"
    impact = ImpactSet(
        event_id=event_id,
        event_type=event_type,
        counterparty_ids=counterparty_ids,
        reason=reason,
        occurred_at=datetime.now(UTC),
        price_moves=_simulated_move(ticker, pct_change, base_feed) if counterparty_ids else [],
    )

    price_scenario = PriceScenario(event_type=event_type, ticker_deltas={ticker: pct_change})
    shocked_feed = SimulatedMarketFeed(price_scenario=price_scenario, base_feed=base_feed)
    graph = build_orchestrator_graph(
        session_factory=session_factory, market_feed=shocked_feed, settings=settings
    )

    results: list[SimulatedCounterpartyResult] = []
    for counterparty_id in counterparty_ids:
        try:
            outcome = dispatch_trigger(graph, impact, counterparty_id, session_factory)
        # GuardrailError (MM-113): a blocked or unscreenable LLM call holds this
        # counterparty's call -- reported, never raised on unscreened text.
        except (
            PricingError,
            CSATermsUnavailableError,
            MarketDataUnavailableError,
            GuardrailError,
            CounterpartyBusyError,
        ) as exc:
            results.append(
                SimulatedCounterpartyResult(counterparty_id=counterparty_id, error=str(exc))
            )
            continue

        results.append(
            SimulatedCounterpartyResult(
                counterparty_id=counterparty_id,
                thread_id=outcome.thread_id,
                breached=outcome.breached,
                call_amount=outcome.call_amount,
                action=outcome.action.value,
                detail=outcome.detail,
            )
        )

    return SimulateEventResponse(
        event_type=event_type.value, reason=reason, affected_counterparties=results
    )
