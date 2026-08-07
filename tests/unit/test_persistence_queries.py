from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from calc.models import PricingError
from persistence.db.models import (
    Base,
    CollateralItemORM,
    CounterpartyORM,
    LatestPriceORM,
    PortfolioORM,
    PositionORM,
    PriceHistoryORM,
    ReferenceRateORM,
)
from persistence.queries import (
    collateral_held,
    collateral_held_for_counterparties,
    get_counterparty,
    latest_closes_before,
    latest_prices,
    latest_vix,
    list_counterparties,
    load_positions,
    load_positions_for_counterparties,
)
from persistence.queries import price_history as price_history_rows


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


class TestListCounterparties:
    def test_returns_every_counterparty(self, session_factory) -> None:
        with session_factory() as session:
            session.add(CounterpartyORM(id="CP-1", name="Alpha", type="Bank", country="US"))
            session.add(CounterpartyORM(id="CP-2", name="Beta", type="Hedge Fund", country="UK"))
            session.commit()

        with session_factory() as session:
            result = list_counterparties(session)

        assert {cp.id for cp in result} == {"CP-1", "CP-2"}
        assert {cp.name for cp in result} == {"Alpha", "Beta"}

    def test_empty_when_no_counterparties(self, session_factory) -> None:
        with session_factory() as session:
            assert list_counterparties(session) == []


class TestGetCounterparty:
    def test_returns_the_matching_counterparty(self, session_factory) -> None:
        with session_factory() as session:
            session.add(CounterpartyORM(id="CP-1", name="Alpha", type="Bank", country="US"))
            session.add(CounterpartyORM(id="CP-2", name="Beta", type="Hedge Fund", country="UK"))
            session.commit()

        with session_factory() as session:
            result = get_counterparty(session, "CP-2")

        assert result is not None
        assert result.id == "CP-2"
        assert result.name == "Beta"

    def test_none_for_unknown_counterparty(self, session_factory) -> None:
        with session_factory() as session:
            assert get_counterparty(session, "CP-404") is None


class TestLoadPositions:
    def test_returns_positions_for_the_counterparty(self, session_factory) -> None:
        with session_factory() as session:
            session.add(CounterpartyORM(id="CP-1", name="CP-1", type="Bank", country="US"))
            session.add(PortfolioORM(id="PF-1", counterparty_id="CP-1", currency="USD"))
            session.add(
                PositionORM(
                    id="POS-1",
                    portfolio_id="PF-1",
                    ticker="AAPL",
                    asset_class="equity",
                    quantity=10,
                    trade_date=date(2026, 1, 1),
                )
            )
            session.commit()

        with session_factory() as session:
            result = load_positions(session, "CP-1")

        assert len(result) == 1
        assert result[0].ticker == "AAPL"

    def test_empty_for_unknown_counterparty(self, session_factory) -> None:
        with session_factory() as session:
            assert load_positions(session, "CP-404") == []


class TestLoadPositionsForCounterparties:
    def test_groups_positions_by_counterparty(self, session_factory) -> None:
        with session_factory() as session:
            session.add(CounterpartyORM(id="CP-1", name="CP-1", type="Bank", country="US"))
            session.add(CounterpartyORM(id="CP-2", name="CP-2", type="Bank", country="US"))
            session.add(PortfolioORM(id="PF-1", counterparty_id="CP-1", currency="USD"))
            session.add(PortfolioORM(id="PF-2", counterparty_id="CP-2", currency="USD"))
            session.add(
                PositionORM(
                    id="POS-1",
                    portfolio_id="PF-1",
                    ticker="AAPL",
                    asset_class="equity",
                    quantity=10,
                    trade_date=date(2026, 1, 1),
                )
            )
            session.add(
                PositionORM(
                    id="POS-2",
                    portfolio_id="PF-2",
                    ticker="TSLA",
                    asset_class="equity",
                    quantity=5,
                    trade_date=date(2026, 1, 1),
                )
            )
            session.commit()

        with session_factory() as session:
            result = load_positions_for_counterparties(session, ["CP-1", "CP-2"])

        assert {p.ticker for p in result["CP-1"]} == {"AAPL"}
        assert {p.ticker for p in result["CP-2"]} == {"TSLA"}

    def test_counterparty_with_no_positions_is_simply_absent(self, session_factory) -> None:
        with session_factory() as session:
            session.add(CounterpartyORM(id="CP-1", name="CP-1", type="Bank", country="US"))
            session.commit()

        with session_factory() as session:
            result = load_positions_for_counterparties(session, ["CP-1"])

        assert result == {}

    def test_empty_list_of_counterparties_returns_empty_dict(self, session_factory) -> None:
        with session_factory() as session:
            assert load_positions_for_counterparties(session, []) == {}


class TestCollateralHeldForCounterparties:
    def test_sums_haircut_adjusted_value_per_counterparty(self, session_factory) -> None:
        with session_factory() as session:
            session.add(CounterpartyORM(id="CP-1", name="CP-1", type="Bank", country="US"))
            session.add(CounterpartyORM(id="CP-2", name="CP-2", type="Bank", country="US"))
            session.add(
                CollateralItemORM(
                    id="COLL-1",
                    counterparty_id="CP-1",
                    collateral_type="cash",
                    value_usd=100_000.0,
                    haircut_pct=0.0,
                )
            )
            session.add(
                CollateralItemORM(
                    id="COLL-2",
                    counterparty_id="CP-1",
                    collateral_type="security",
                    value_usd=50_000.0,
                    haircut_pct=0.1,
                )
            )
            session.add(
                CollateralItemORM(
                    id="COLL-3",
                    counterparty_id="CP-2",
                    collateral_type="cash",
                    value_usd=10_000.0,
                    haircut_pct=0.0,
                )
            )
            session.commit()

        with session_factory() as session:
            result = collateral_held_for_counterparties(session, ["CP-1", "CP-2"])

        assert result == {"CP-1": 100_000.0 + 45_000.0, "CP-2": 10_000.0}

    def test_counterparty_with_no_collateral_gets_zero_not_absent(self, session_factory) -> None:
        with session_factory() as session:
            session.add(CounterpartyORM(id="CP-1", name="CP-1", type="Bank", country="US"))
            session.commit()

        with session_factory() as session:
            result = collateral_held_for_counterparties(session, ["CP-1"])

        assert result == {"CP-1": 0.0}

    def test_empty_list_of_counterparties_returns_empty_dict(self, session_factory) -> None:
        with session_factory() as session:
            assert collateral_held_for_counterparties(session, []) == {}


class TestCollateralHeld:
    def test_sums_haircut_adjusted_value(self, session_factory) -> None:
        with session_factory() as session:
            session.add(CounterpartyORM(id="CP-1", name="CP-1", type="Bank", country="US"))
            session.add(
                CollateralItemORM(
                    id="COLL-1",
                    counterparty_id="CP-1",
                    collateral_type="cash",
                    value_usd=100_000.0,
                    haircut_pct=0.0,
                )
            )
            session.add(
                CollateralItemORM(
                    id="COLL-2",
                    counterparty_id="CP-1",
                    collateral_type="security",
                    value_usd=50_000.0,
                    haircut_pct=0.1,
                )
            )
            session.commit()

        with session_factory() as session:
            assert collateral_held(session, "CP-1") == 100_000.0 + 45_000.0

    def test_zero_when_no_collateral(self, session_factory) -> None:
        with session_factory() as session:
            assert collateral_held(session, "CP-1") == 0.0


class TestLatestVix:
    def test_returns_most_recent_value(self, session_factory) -> None:
        with session_factory() as session:
            session.add(
                ReferenceRateORM(series_id="VIXCLS", rate_date=date(2026, 1, 1), value=18.0)
            )
            session.add(
                ReferenceRateORM(series_id="VIXCLS", rate_date=date(2026, 1, 3), value=22.0)
            )
            session.commit()

        with session_factory() as session:
            assert latest_vix(session) == 22.0

    def test_raises_when_no_vix_data(self, session_factory) -> None:
        with session_factory() as session, pytest.raises(PricingError, match="VIXCLS"):
            latest_vix(session)


class TestLatestPrices:
    def test_returns_only_the_requested_tickers(self, session_factory) -> None:
        as_of = datetime(2026, 7, 31, 14, 0, tzinfo=UTC)
        with session_factory() as session:
            session.add_all(
                [
                    LatestPriceORM(
                        ticker="AAPL",
                        price=200.0,
                        currency="USD",
                        source="yfinance",
                        as_of=as_of,
                        updated_at=as_of,
                    ),
                    LatestPriceORM(
                        ticker="TSLA",
                        price=88.0,
                        currency="USD",
                        source="yfinance",
                        as_of=as_of,
                        updated_at=as_of,
                    ),
                ]
            )
            session.commit()

        with session_factory() as session:
            result = latest_prices(session, ["AAPL"])

        assert set(result) == {"AAPL"}
        assert result["AAPL"].price == 200.0
        assert result["AAPL"].source == "yfinance"

    def test_empty_list_of_tickers_returns_empty_dict(self, session_factory) -> None:
        with session_factory() as session:
            assert latest_prices(session, []) == {}

    def test_ticker_with_no_row_is_simply_absent(self, session_factory) -> None:
        with session_factory() as session:
            assert latest_prices(session, ["AAPL"]) == {}


class TestLatestClosesBefore:
    def test_returns_most_recent_close_per_ticker_batched(self, session_factory) -> None:
        with session_factory() as session:
            session.add_all(
                [
                    PriceHistoryORM(
                        ticker="AAPL",
                        price_date=date(2026, 7, 29),
                        price=195.0,
                        currency="USD",
                        source="yfinance",
                    ),
                    PriceHistoryORM(
                        ticker="AAPL",
                        price_date=date(2026, 7, 30),
                        price=200.0,
                        currency="USD",
                        source="yfinance",
                    ),
                    PriceHistoryORM(
                        ticker="TSLA",
                        price_date=date(2026, 7, 30),
                        price=88.0,
                        currency="USD",
                        source="yfinance",
                    ),
                ]
            )
            session.commit()

        with session_factory() as session:
            result = latest_closes_before(
                session, ["AAPL", "TSLA"], datetime(2026, 7, 31, tzinfo=UTC)
            )

        assert result == {"AAPL": 200.0, "TSLA": 88.0}

    def test_excludes_a_row_on_or_after_the_cutoff_date(self, session_factory) -> None:
        with session_factory() as session:
            session.add(
                PriceHistoryORM(
                    ticker="AAPL",
                    price_date=date(2026, 7, 31),
                    price=210.0,
                    currency="USD",
                    source="yfinance",
                )
            )
            session.commit()

        with session_factory() as session:
            result = latest_closes_before(session, ["AAPL"], datetime(2026, 7, 31, tzinfo=UTC))

        assert result == {}

    def test_ticker_with_no_history_is_simply_absent(self, session_factory) -> None:
        with session_factory() as session:
            result = latest_closes_before(session, ["ZZZZ"], datetime(2026, 7, 31, tzinfo=UTC))

        assert result == {}

    def test_empty_list_of_tickers_returns_empty_dict(self, session_factory) -> None:
        with session_factory() as session:
            assert latest_closes_before(session, [], datetime(2026, 7, 31, tzinfo=UTC)) == {}


class TestPriceHistory:
    def test_respects_days_cutoff_and_orders_ascending(self, session_factory) -> None:
        today = datetime.now(UTC).date()
        with session_factory() as session:
            session.add_all(
                [
                    PriceHistoryORM(
                        ticker="AAPL",
                        price_date=today - timedelta(days=40),
                        price=180.0,
                        currency="USD",
                        source="yfinance",
                    ),
                    PriceHistoryORM(
                        ticker="AAPL",
                        price_date=today - timedelta(days=2),
                        price=195.0,
                        currency="USD",
                        source="yfinance",
                    ),
                    PriceHistoryORM(
                        ticker="AAPL",
                        price_date=today - timedelta(days=1),
                        price=200.0,
                        currency="USD",
                        source="yfinance",
                    ),
                ]
            )
            session.commit()

        with session_factory() as session:
            result = price_history_rows(session, "AAPL", days=30)

        assert [entry.price for entry in result] == [195.0, 200.0]
        assert result[0].date < result[1].date

    def test_empty_for_unknown_ticker(self, session_factory) -> None:
        with session_factory() as session:
            assert price_history_rows(session, "ZZZZ") == []
