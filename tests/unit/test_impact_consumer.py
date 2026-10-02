"""MM-121: impact sets -> margin-call runs, exactly once per (event, counterparty)."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from agents.csa_rag import CSATermsUnavailableError
from persistence.db.models import Base, ProcessedEventORM
from streaming.impact_consumer import claim_run, handle_impact, release_run, run_claim_id
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

    with patch("streaming.impact_consumer.start_run") as start_run:
        first = handle_impact(impact, session_factory, graph_factory)
        second = handle_impact(impact, session_factory, graph_factory)

    assert first == [f"{impact.event_id}:CP-1", f"{impact.event_id}:CP-2"]
    assert second == []
    assert start_run.call_count == 2
    graph_factory.assert_called_once()  # built once, lazily
    assert sorted(_claims(session_factory)) == [run_claim_id(t) for t in first]


def test_nothing_to_run_builds_no_graph(session_factory):
    graph_factory = MagicMock()

    assert handle_impact(_impact([]), session_factory, graph_factory) == []
    graph_factory.assert_not_called()


def test_a_known_business_error_is_held_not_retried(session_factory):
    impact = _impact(["CP-1"])
    with patch(
        "streaming.impact_consumer.start_run",
        side_effect=CSATermsUnavailableError("no CSA for CP-1"),
    ) as start_run:
        assert handle_impact(impact, session_factory, MagicMock()) == []
        assert handle_impact(impact, session_factory, MagicMock()) == []

    start_run.assert_called_once()  # stays claimed: a retry would only repeat the LLM calls


def test_an_unexpected_error_releases_the_claim_and_raises(session_factory):
    impact = _impact(["CP-1"])
    with (
        patch("streaming.impact_consumer.start_run", side_effect=RuntimeError("db blip")),
        pytest.raises(RuntimeError),
    ):
        handle_impact(impact, session_factory, MagicMock())

    assert _claims(session_factory) == []  # redelivery will try again
    with patch("streaming.impact_consumer.start_run") as start_run:
        assert handle_impact(impact, session_factory, MagicMock()) == [f"{impact.event_id}:CP-1"]
    start_run.assert_called_once()


def test_run_state_carries_the_impact_and_counterparty(session_factory):
    impact = _impact(["CP-7"])
    with patch("streaming.impact_consumer.start_run") as start_run:
        handle_impact(impact, session_factory, MagicMock())

    state = start_run.call_args.args[1]
    assert (state.correlation_id, state.counterparty_id) == (impact.event_id, "CP-7")
    assert state.impact == impact


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
