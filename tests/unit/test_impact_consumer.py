"""MM-121: impact sets -> margin-call runs, exactly once per (event, counterparty).
MM-125: each counterparty is dispatched through the margin-call policy."""

from datetime import UTC, date, datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from agents.csa_rag import CSATermsUnavailableError
from agents.margin_policy import CounterpartyBusyError, TriggerAction, TriggerOutcome
from persistence.db.models import Base, CounterpartyORM, PortfolioORM, ProcessedEventORM
from streaming.impact_consumer import (
    claim_run,
    daily_margin_run_impact,
    handle_impact,
    release_run,
    run_claim_id,
)
from streaming.schemas import ImpactSet, MarketEventType


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _impact(counterparties: list[str]) -> ImpactSet:
    return ImpactSet(
        event_id="MU:2026-10-02T15:00:00+00:00:yfinance",
        event_type=MarketEventType.PRICE_SHOCK,
        counterparty_ids=counterparties,
        reason="MU moved 20.0% vs prior close",
        occurred_at=datetime(2026, 10, 2, 15, tzinfo=UTC),
    )


def _started(graph, impact, counterparty_id, session_factory) -> TriggerOutcome:
    return TriggerOutcome(
        counterparty_id=counterparty_id,
        action=TriggerAction.STARTED,
        thread_id=f"{impact.event_id}:{counterparty_id}",
    )


def _dispatch(**kwargs):
    return patch("streaming.impact_consumer.dispatch_trigger", **kwargs)


def _claims(session_factory) -> list[str]:
    with session_factory() as session:
        return list(session.execute(select(ProcessedEventORM.event_id)).scalars())


def test_claim_is_exclusive_until_released(session_factory):
    assert claim_run(session_factory, "evt:CP-1") is True
    assert claim_run(session_factory, "evt:CP-1") is False

    release_run(session_factory, "evt:CP-1")
    assert claim_run(session_factory, "evt:CP-1") is True


def test_one_run_per_counterparty_and_none_on_redelivery(session_factory):
    graph_factory = MagicMock()
    impact = _impact(["CP-1", "CP-2"])

    with _dispatch(side_effect=_started) as dispatch:
        first = handle_impact(impact, session_factory, graph_factory)
        second = handle_impact(impact, session_factory, graph_factory)

    threads = [o.thread_id for o in first]
    assert threads == [f"{impact.event_id}:CP-1", f"{impact.event_id}:CP-2"]
    assert second == []
    assert dispatch.call_count == 2
    graph_factory.assert_called_once()  # built once, lazily
    assert sorted(_claims(session_factory)) == [run_claim_id(t) for t in threads]


def test_nothing_to_run_builds_no_graph(session_factory):
    graph_factory = MagicMock()

    assert handle_impact(_impact([]), session_factory, graph_factory) == []
    graph_factory.assert_not_called()


def test_a_known_business_error_is_held_not_retried(session_factory):
    impact = _impact(["CP-1"])
    with _dispatch(side_effect=CSATermsUnavailableError("no CSA for CP-1")) as dispatch:
        assert handle_impact(impact, session_factory, MagicMock()) == []
        assert handle_impact(impact, session_factory, MagicMock()) == []

    dispatch.assert_called_once()  # stays claimed: a retry would only repeat the LLM calls


def test_an_unexpected_error_releases_the_claim_and_raises(session_factory):
    impact = _impact(["CP-1"])
    with _dispatch(side_effect=RuntimeError("db blip")), pytest.raises(RuntimeError):
        handle_impact(impact, session_factory, MagicMock())

    assert _claims(session_factory) == []  # redelivery will try again
    with _dispatch(side_effect=_started) as dispatch:
        outcomes = handle_impact(impact, session_factory, MagicMock())
    assert [o.thread_id for o in outcomes] == [f"{impact.event_id}:CP-1"]
    dispatch.assert_called_once()


def test_dispatch_gets_the_impact_and_counterparty(session_factory):
    impact = _impact(["CP-7"])
    graph_factory = MagicMock()
    with _dispatch(side_effect=_started) as dispatch:
        handle_impact(impact, session_factory, graph_factory)

    graph, dispatched, counterparty_id, factory = dispatch.call_args.args
    assert graph is graph_factory.return_value
    assert (dispatched, counterparty_id, factory) == (impact, "CP-7", session_factory)


def test_a_busy_counterparty_is_retried_after_the_others(session_factory):
    """MM-125: another trigger holds CP-1's lease. CP-2 is still dispatched;
    CP-1's claim is released and the error makes the message redeliver."""
    impact = _impact(["CP-1", "CP-2"])

    def _busy_cp1(graph, impact, counterparty_id, factory):
        if counterparty_id == "CP-1":
            raise CounterpartyBusyError("CP-1 busy")
        return _started(graph, impact, counterparty_id, factory)

    with _dispatch(side_effect=_busy_cp1), pytest.raises(CounterpartyBusyError, match="CP-1"):
        handle_impact(impact, session_factory, MagicMock())

    assert _claims(session_factory) == [run_claim_id(f"{impact.event_id}:CP-2")]
    with _dispatch(side_effect=_started) as dispatch:
        outcomes = handle_impact(impact, session_factory, MagicMock())
    assert [o.counterparty_id for o in outcomes] == ["CP-1"]  # CP-2 was already done
    dispatch.assert_called_once()


def test_daily_margin_run_names_every_counterparty_with_a_book_once_a_day(session_factory):
    with session_factory() as session:
        for cp in ("CP-2", "CP-1"):
            session.add(CounterpartyORM(id=cp, name=cp, type="Bank", country="US"))
            session.add(PortfolioORM(id=f"PF-{cp}", counterparty_id=cp, currency="USD"))
        session.add(CounterpartyORM(id="CP-9", name="CP-9", type="Bank", country="US"))
        session.commit()

        impact = daily_margin_run_impact(session, date(2026, 10, 2))

    assert impact.event_id == "daily-margin-run:2026-10-02"
    assert impact.event_type == MarketEventType.DAILY_MARGIN_RUN
    assert impact.counterparty_ids == ["CP-1", "CP-2"]  # CP-9 has no book
    assert impact.price_moves == []  # never gated


def test_claim_rows_do_not_collide_with_event_dedup_rows(session_factory):
    """Event Agent dedup rows use the bare event id; run claims are prefixed."""
    with session_factory() as session:
        session.add(ProcessedEventORM(event_id="evt:CP-1", processed_at=datetime.now(UTC)))
        session.commit()

    assert claim_run(session_factory, "evt:CP-1") is True


def test_live_graph_prices_off_the_configured_feed(session_factory):
    from config.settings import Settings
    from streaming import pubsub_dispatch

    settings = Settings(_env_file=None)
    with (
        patch.object(pubsub_dispatch, "get_market_feed") as feed,
        patch.object(pubsub_dispatch, "build_orchestrator_graph") as build,
    ):
        factory = pubsub_dispatch.live_graph_factory(settings, session_factory)
        build.assert_not_called()  # lazy: no graph until an impact needs one
        factory()

    assert build.call_args.kwargs == {
        "session_factory": session_factory,
        "market_feed": feed.return_value,
        "settings": settings,
    }
