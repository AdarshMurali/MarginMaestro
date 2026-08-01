from datetime import date

from calc.trade_diff import BreakType, diff_trades, generate_counterparty_view, reconcile
from persistence.models import AssetClass, Position


def _position(id_: str, ticker: str, quantity: float) -> Position:
    return Position(
        id=id_,
        portfolio_id="PF-1",
        ticker=ticker,
        asset_class=AssetClass.EQUITY,
        quantity=quantity,
        trade_date=date(2026, 1, 1),
    )


OUR_POSITIONS = [
    _position("POS-1", "AAPL", 100.0),
    _position("POS-2", "MSFT", 50.0),
    _position("POS-3", "TSLA", 25.0),
]


class TestDiffTrades:
    def test_no_breaks_when_identical(self) -> None:
        counterparty = [_position("POS-1", "AAPL", 100.0), _position("POS-2", "MSFT", 50.0)]
        our = [_position("POS-1", "AAPL", 100.0), _position("POS-2", "MSFT", 50.0)]

        assert diff_trades(our, counterparty) == []

    def test_detects_quantity_mismatch(self) -> None:
        our = [_position("POS-1", "AAPL", 100.0)]
        counterparty = [_position("POS-1", "AAPL", 80.0)]

        breaks = diff_trades(our, counterparty)

        assert len(breaks) == 1
        assert breaks[0].ticker == "AAPL"
        assert breaks[0].break_type == BreakType.QUANTITY_MISMATCH
        assert breaks[0].our_quantity == 100.0
        assert breaks[0].counterparty_quantity == 80.0

    def test_detects_missing_in_counterparty_view(self) -> None:
        our = [_position("POS-1", "AAPL", 100.0), _position("POS-2", "MSFT", 50.0)]
        counterparty = [_position("POS-1", "AAPL", 100.0)]

        breaks = diff_trades(our, counterparty)

        assert len(breaks) == 1
        assert breaks[0].ticker == "MSFT"
        assert breaks[0].break_type == BreakType.MISSING_IN_COUNTERPARTY_VIEW
        assert breaks[0].our_quantity == 50.0
        assert breaks[0].counterparty_quantity is None

    def test_detects_extra_in_counterparty_view(self) -> None:
        our = [_position("POS-1", "AAPL", 100.0)]
        counterparty = [_position("POS-1", "AAPL", 100.0), _position("POS-2", "MSFT", 30.0)]

        breaks = diff_trades(our, counterparty)

        assert len(breaks) == 1
        assert breaks[0].ticker == "MSFT"
        assert breaks[0].break_type == BreakType.EXTRA_IN_COUNTERPARTY_VIEW
        assert breaks[0].our_quantity is None
        assert breaks[0].counterparty_quantity == 30.0

    def test_multiple_breaks_isolated_independently(self) -> None:
        our = [_position("POS-1", "AAPL", 100.0), _position("POS-2", "MSFT", 50.0)]
        counterparty = [_position("POS-1", "AAPL", 90.0), _position("POS-3", "TSLA", 10.0)]

        breaks = diff_trades(our, counterparty)

        by_ticker = {b.ticker: b for b in breaks}
        assert by_ticker["AAPL"].break_type == BreakType.QUANTITY_MISMATCH
        assert by_ticker["MSFT"].break_type == BreakType.MISSING_IN_COUNTERPARTY_VIEW
        assert by_ticker["TSLA"].break_type == BreakType.EXTRA_IN_COUNTERPARTY_VIEW


class TestGenerateCounterpartyView:
    def test_deterministic_for_the_same_seed(self) -> None:
        view_a = generate_counterparty_view(OUR_POSITIONS, seed=7)
        view_b = generate_counterparty_view(OUR_POSITIONS, seed=7)

        assert view_a == view_b

    def test_differs_for_a_different_seed(self) -> None:
        view_a = generate_counterparty_view(OUR_POSITIONS, seed=1)
        view_b = generate_counterparty_view(OUR_POSITIONS, seed=2)

        assert view_a != view_b

    def test_never_perturbs_the_input_list_in_place(self) -> None:
        original_quantities = [p.quantity for p in OUR_POSITIONS]

        generate_counterparty_view(OUR_POSITIONS, seed=3)

        assert [p.quantity for p in OUR_POSITIONS] == original_quantities


class TestReconcile:
    def test_agreed_within_tolerance_skips_diff_even_if_trades_differ(self) -> None:
        our = [_position("POS-1", "AAPL", 100.0)]
        counterparty = [_position("POS-1", "AAPL", 80.0)]

        result = reconcile(
            our,
            counterparty,
            our_total=1_000_000.0,
            counterparty_total=1_000_050.0,
            tolerance=100.0,
        )

        assert result.agreed is True
        assert result.break_items == []

    def test_disagreed_beyond_tolerance_isolates_breaks(self) -> None:
        our = [_position("POS-1", "AAPL", 100.0)]
        counterparty = [_position("POS-1", "AAPL", 80.0)]

        result = reconcile(
            our, counterparty, our_total=1_000_000.0, counterparty_total=900_000.0, tolerance=100.0
        )

        assert result.agreed is False
        assert len(result.break_items) == 1
        assert result.break_items[0].break_type == BreakType.QUANTITY_MISMATCH

    def test_exact_tolerance_boundary_is_agreed(self) -> None:
        result = reconcile([], [], our_total=1_000.0, counterparty_total=900.0, tolerance=100.0)

        assert result.agreed is True
