from datetime import UTC, date, datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from agents.csa_rag import CSATermsUnavailableError
from api.simulate import trigger_simulation
from config.settings import Settings
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
from streaming.schemas import MarketEventType


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _seed_counterparty(
    session_factory, counterparty_id: str, ticker: str, prior_price: float
) -> None:
    with session_factory() as session:
        session.add(
            CounterpartyORM(id=counterparty_id, name=counterparty_id, type="Bank", country="US")
        )
        portfolio_id = f"PF-{counterparty_id}"
        session.add(PortfolioORM(id=portfolio_id, counterparty_id=counterparty_id, currency="USD"))
        session.add(
            PositionORM(
                id=f"POS-{counterparty_id}",
                portfolio_id=portfolio_id,
                ticker=ticker,
                asset_class="equity",
                quantity=1000,
                trade_date=date(2026, 1, 1),
            )
        )
        session.merge(
            PriceHistoryORM(
                ticker=ticker,
                price_date=date(2026, 7, 30),
                price=prior_price,
                currency="USD",
                source="test",
            )
        )
        session.merge(ReferenceRateORM(series_id="VIXCLS", rate_date=date(2026, 7, 30), value=20.0))
        session.add(
            CollateralItemORM(
                id=f"COLL-{counterparty_id}",
                counterparty_id=counterparty_id,
                collateral_type="cash",
                value_usd=0.0,
                haircut_pct=0.0,
            )
        )
        session.commit()


def _csa_result(counterparty_id: str, threshold: float = 1_000.0) -> CSATermsResult:
    return CSATermsResult(
        counterparty_id=counterparty_id,
        threshold=threshold,
        mta=1.0,
        currency="USD",
        eligible_collateral=["cash"],
        haircuts={"cash": 0.0},
        rating_triggers=[],
        citations=[],
    )


def _fake_base_feed(price: float = 500.0) -> MagicMock:
    feed = MagicMock()

    def _get_prices(tickers: list[str]) -> dict[str, PriceQuote]:
        return {
            t: PriceQuote(ticker=t, price=price, as_of=datetime.now(UTC), source="test")
            for t in tickers
        }

    feed.get_prices.side_effect = _get_prices
    return feed


class TestTriggerSimulation:
    def test_no_affected_counterparties_returns_empty_list(self, session_factory) -> None:
        with session_factory() as session:
            result = trigger_simulation(
                MarketEventType.PRICE_SHOCK,
                "TSLA",
                -0.12,
                session,
                session_factory,
                Settings(_env_file=None),
                base_feed=_fake_base_feed(),
            )

        assert result.affected_counterparties == []
        assert result.event_type == "price_shock"

    def test_affected_counterparty_gets_a_real_run_and_breach_result(self, session_factory) -> None:
        _seed_counterparty(session_factory, "CP-SIM", "TSLA", prior_price=100.0)

        with (
            patch("agents.orchestrator.answer_csa_terms", return_value=_csa_result("CP-SIM")),
            session_factory() as session,
        ):
            result = trigger_simulation(
                MarketEventType.PRICE_SHOCK,
                "TSLA",
                -0.12,
                session,
                session_factory,
                Settings(_env_file=None),
                base_feed=_fake_base_feed(price=500.0),
            )

        assert len(result.affected_counterparties) == 1
        item = result.affected_counterparties[0]
        assert item.counterparty_id == "CP-SIM"
        assert item.error is None
        assert item.thread_id is not None and item.thread_id.endswith(":CP-SIM")
        # -12% delta: 500 * 0.88 = 440, still a real breach against a
        # threshold of 1,000.
        assert item.breached is True
        assert item.call_amount is not None and item.call_amount > 0

    def test_unaffected_counterparty_is_not_included(self, session_factory) -> None:
        # Holds a ticker that isn't the one being shocked.
        _seed_counterparty(session_factory, "CP-UNRELATED", "AAPL", prior_price=100.0)

        with session_factory() as session:
            result = trigger_simulation(
                MarketEventType.PRICE_SHOCK,
                "TSLA",
                -0.12,
                session,
                session_factory,
                Settings(_env_file=None),
                base_feed=_fake_base_feed(),
            )

        assert result.affected_counterparties == []

    def test_per_counterparty_error_does_not_fail_the_whole_request(self, session_factory) -> None:
        _seed_counterparty(session_factory, "CP-NOCSA", "TSLA", prior_price=100.0)

        with (
            patch(
                "agents.orchestrator.answer_csa_terms",
                side_effect=CSATermsUnavailableError("no CSA doc"),
            ),
            session_factory() as session,
        ):
            result = trigger_simulation(
                MarketEventType.PRICE_SHOCK,
                "TSLA",
                -0.12,
                session,
                session_factory,
                Settings(_env_file=None),
                base_feed=_fake_base_feed(),
            )

        assert len(result.affected_counterparties) == 1
        item = result.affected_counterparties[0]
        assert item.error is not None
        assert item.thread_id is None
        assert item.breached is None

    def test_reason_mentions_the_ticker_and_signed_pct(self, session_factory) -> None:
        with session_factory() as session:
            result = trigger_simulation(
                MarketEventType.VOL_SPIKE,
                "BTC-USD",
                -0.18,
                session,
                session_factory,
                Settings(_env_file=None),
                base_feed=_fake_base_feed(),
            )

        assert "vol_spike" in result.reason
        assert "BTC-USD" in result.reason
        assert "-18.0%" in result.reason

    def test_positive_pct_change_is_supported(self, session_factory) -> None:
        _seed_counterparty(session_factory, "CP-UP", "TSLA", prior_price=100.0)

        with (
            patch("agents.orchestrator.answer_csa_terms", return_value=_csa_result("CP-UP")),
            session_factory() as session,
        ):
            result = trigger_simulation(
                MarketEventType.PRICE_SHOCK,
                "TSLA",
                0.20,
                session,
                session_factory,
                Settings(_env_file=None),
                base_feed=_fake_base_feed(price=100.0),
            )

        assert "+20.0%" in result.reason
        # A real counterparty holding TSLA is still evaluated even though an
        # upward move can't itself breach a VM threshold.
        assert len(result.affected_counterparties) == 1
