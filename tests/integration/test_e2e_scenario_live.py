"""Full-lifecycle E2E scenario test (MM-44, closing Phase 6): shock -> call
-> Slack -> SLA breach -> ServiceNow incident, against real accounts.
Excluded from the default/CI test run (see the `live` marker in
pyproject.toml).

Real: Slack send, ServiceNow incident creation, Azure SQL persistence
(checkpointing + positions/prices/collateral reads) -- these are MM-44's
literal exit criteria ("real Slack + ServiceNow"). CSA-RAG is mocked, same
as every other orchestrator-level test in this codebase (MM-36 through
MM-43) -- it's exercised for real in its own dedicated MM-26/27 tests, not
here. Uses a dedicated CP-E2E counterparty rather than a real corpus
counterparty (CP-1..8) specifically to avoid colliding with those
counterparties' real generated portfolio/collateral data already sitting
in the local dev DB (discovered while writing this test: every corpus
counterparty already has a real portfolio from an earlier batch_loader
run, with substantial existing collateral that would make a believable
single-ticker shock impractical to construct).

Run explicitly with: pytest -m live tests/integration/test_e2e_scenario_live.py
"""

from datetime import UTC, date, datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import DBAPIError

from agents.orchestrator import (
    MarginCallState,
    build_orchestrator_graph,
    resume_run,
    start_run,
    thread_id_for,
)
from config.settings import get_settings
from persistence.db.bootstrap import ensure_database_exists
from persistence.db.engine import get_engine, get_session_factory
from persistence.db.models import (
    Base,
    CollateralItemORM,
    CounterpartyORM,
    PortfolioORM,
    PositionORM,
    PriceHistoryORM,
    ReferenceRateORM,
)
from rag.models import CSATermsResult
from streaming.market_feed import PriceQuote
from streaming.schemas import ImpactSet, MarketEventType

pytestmark = pytest.mark.live

COUNTERPARTY_ID = "CP-E2E"
SHOCK_TICKER = "TSLA"
SHOCK_QUANTITY = 2000
PRIOR_PRICE = 100.0
SHOCKED_PRICE = 500.0
THRESHOLD = 100_000.0
MTA = 10_000.0


@pytest.fixture(scope="module")
def db_session_factory():
    settings = get_settings()
    try:
        ensure_database_exists(settings)
        engine = get_engine(settings)
        Base.metadata.create_all(engine)
        engine.dispose()
    except DBAPIError as exc:
        pytest.skip(f"No reachable database for integration tests: {exc}")
    yield get_session_factory(settings)


def _seed_shock_scenario(session_factory) -> None:
    with session_factory() as session:
        session.merge(
            CounterpartyORM(id=COUNTERPARTY_ID, name="E2E Test Capital", type="Bank", country="US")
        )
        session.merge(
            PortfolioORM(
                id=f"PF-{COUNTERPARTY_ID}", counterparty_id=COUNTERPARTY_ID, currency="USD"
            )
        )
        session.merge(
            PositionORM(
                id=f"POS-{COUNTERPARTY_ID}-{SHOCK_TICKER}",
                portfolio_id=f"PF-{COUNTERPARTY_ID}",
                ticker=SHOCK_TICKER,
                asset_class="equity",
                quantity=SHOCK_QUANTITY,
                trade_date=date(2026, 1, 1),
            )
        )
        session.merge(
            PriceHistoryORM(
                ticker=SHOCK_TICKER,
                price_date=date(2026, 7, 30),
                price=PRIOR_PRICE,
                currency="USD",
                source="yfinance",
            )
        )
        session.merge(ReferenceRateORM(series_id="VIXCLS", rate_date=date(2026, 7, 30), value=20.0))
        session.merge(
            CollateralItemORM(
                id=f"COL-{COUNTERPARTY_ID}",
                counterparty_id=COUNTERPARTY_ID,
                collateral_type="cash",
                value_usd=0.0,
                haircut_pct=0.0,
            )
        )
        session.commit()


def _shock_market_feed() -> MagicMock:
    market_feed = MagicMock()
    market_feed.get_prices.return_value = {
        SHOCK_TICKER: PriceQuote(
            ticker=SHOCK_TICKER, price=SHOCKED_PRICE, as_of=datetime.now(UTC), source="yfinance"
        )
    }
    return market_feed


def _mock_csa_result() -> CSATermsResult:
    return CSATermsResult(
        counterparty_id=COUNTERPARTY_ID,
        threshold=THRESHOLD,
        mta=MTA,
        currency="USD",
        eligible_collateral=["cash"],
        haircuts={"cash": 0.0},
        rating_triggers=[],
        citations=[],
    )


def test_full_lifecycle_shock_to_call_to_slack_to_sla_breach_to_servicenow(
    db_session_factory,
) -> None:
    _seed_shock_scenario(db_session_factory)

    # margin_call_sla_minutes=0 forces an immediate breach on the first
    # check -- other settings (Slack/ServiceNow credentials) still come
    # from the real environment.
    settings = get_settings().model_copy(update={"margin_call_sla_minutes": 0})

    impact = ImpactSet(
        event_id="e2e-shock-1",
        event_type=MarketEventType.PRICE_SHOCK,
        counterparty_ids=[COUNTERPARTY_ID],
        reason=f"{SHOCK_TICKER} moved from {PRIOR_PRICE} to {SHOCKED_PRICE}",
        occurred_at=datetime.now(UTC),
    )

    with patch("agents.orchestrator.answer_csa_terms", return_value=_mock_csa_result()):
        graph = build_orchestrator_graph(
            session_factory=db_session_factory,
            market_feed=_shock_market_feed(),
            settings=settings,
        )
        state = MarginCallState(
            correlation_id="e2e-test", impact=impact, counterparty_id=COUNTERPARTY_ID
        )
        thread_id = thread_id_for(impact, COUNTERPARTY_ID)

        # Shock -> call: breach evaluated against the (mocked) CSA terms.
        paused_at_approval = start_run(graph, state)
        assert "__interrupt__" in paused_at_approval
        assert paused_at_approval["breach_result"].breached is True

        # Call -> Slack: approving sends a real Slack message, then pauses
        # at the SLA timer.
        paused_at_sla = resume_run(graph, thread_id, {"decision": "approved"})
        assert "__interrupt__" in paused_at_sla
        assert paused_at_sla["notification_result"].slack_channel == settings.slack_channel_id

        # SLA breach -> ServiceNow: margin_call_sla_minutes=0 means the
        # very next check is already past the deadline.
        final_result = resume_run(graph, thread_id, {"check": True})

    assert "__interrupt__" not in final_result
    assert final_result["sla_outcome"] == "breached"
    assert final_result["escalation_result"].incident_number.startswith("INC")
