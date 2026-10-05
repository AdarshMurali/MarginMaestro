"""MM-125: the intraday materiality gate and the call rationale -- hand-computed
expected values (equity risk weight 0.15; VIX 20 -> multiplier 1.0)."""

from datetime import date

import pytest

from calc.materiality import (
    below_materiality_rationale,
    event_exposure_impact,
    event_sentence,
    exposure_sentence,
    is_material,
    material_event_rationale,
    money,
)
from calc.models import EventImpact, PriceMove
from persistence.models import AssetClass, Position


def _position(
    ticker: str, quantity: float, asset_class: AssetClass = AssetClass.EQUITY
) -> Position:
    return Position(
        id=f"POS-{ticker}",
        portfolio_id="PF-1",
        ticker=ticker,
        asset_class=asset_class,
        quantity=quantity,
        trade_date=date(2026, 1, 1),
    )


HPE_MOVE = PriceMove(ticker="HPE", from_price=65.07, to_price=69.88)


class TestEventExposureImpact:
    def test_long_position_price_up_increases_exposure(self) -> None:
        # MTM 100 x 50 = 5,000 -> 100 x 55 = 5,500: +500.
        # IM 5,000 x 0.15 = 750 -> 5,500 x 0.15 = 825: +75. Exposure +575.
        impact = event_exposure_impact(
            [_position("AAPL", 100)], [PriceMove(ticker="AAPL", from_price=50, to_price=55)], 20.0
        )

        assert impact.tickers == ["AAPL"]
        assert impact.mtm_change == pytest.approx(500.0)
        assert impact.im_change == pytest.approx(75.0)
        assert impact.exposure_change == pytest.approx(575.0)

    def test_short_position_price_up_reduces_exposure(self) -> None:
        # MTM -5,000 -> -5,500: -500. IM uses |MTM|: 750 -> 825: +75. Net -425.
        impact = event_exposure_impact(
            [_position("AAPL", -100)], [PriceMove(ticker="AAPL", from_price=50, to_price=55)], 20.0
        )

        assert impact.mtm_change == pytest.approx(-500.0)
        assert impact.im_change == pytest.approx(75.0)
        assert impact.exposure_change == pytest.approx(-425.0)

    def test_vix_multiplier_scales_only_the_im_part(self) -> None:
        # VIX 40 -> multiplier 2.0: IM change 75 x 2 = 150; exposure 500 + 150.
        impact = event_exposure_impact(
            [_position("AAPL", 100)], [PriceMove(ticker="AAPL", from_price=50, to_price=55)], 40.0
        )

        assert impact.im_change == pytest.approx(150.0)
        assert impact.exposure_change == pytest.approx(650.0)

    def test_only_positions_in_moved_tickers_count(self) -> None:
        positions = [_position("AAPL", 100), _position("MSFT", 1_000_000)]

        impact = event_exposure_impact(
            positions, [PriceMove(ticker="AAPL", from_price=50, to_price=55)], 20.0
        )

        assert impact.tickers == ["AAPL"]
        assert impact.exposure_change == pytest.approx(575.0)

    def test_several_moved_tickers_add_up(self) -> None:
        # AAPL +575 (above); MSFT 10 x (200 -> 190): MTM -100, IM 300 -> 285: -15.
        positions = [_position("AAPL", 100), _position("MSFT", 10)]
        moves = [
            PriceMove(ticker="AAPL", from_price=50, to_price=55),
            PriceMove(ticker="MSFT", from_price=200, to_price=190),
        ]

        impact = event_exposure_impact(positions, moves, 20.0)

        assert impact.tickers == ["AAPL", "MSFT"]
        assert impact.mtm_change == pytest.approx(400.0)
        assert impact.im_change == pytest.approx(60.0)
        assert impact.exposure_change == pytest.approx(460.0)

    def test_a_book_without_the_moved_ticker_has_zero_impact(self) -> None:
        impact = event_exposure_impact([_position("MSFT", 100)], [HPE_MOVE], 20.0)

        assert impact == EventImpact(tickers=[], mtm_change=0, im_change=0, exposure_change=0)

    def test_hpe_2026_10_02_move_on_the_seeded_books(self) -> None:
        """The live run that motivated MM-125: HPE $65.07 -> $69.88. Seeded
        (seed 42) HPE quantities: CP-1 -439, CP-3 247, CP-7 742."""
        cp1 = event_exposure_impact([_position("HPE", -439)], [HPE_MOVE], 20.0)
        cp3 = event_exposure_impact([_position("HPE", 247)], [HPE_MOVE], 20.0)
        cp7 = event_exposure_impact([_position("HPE", 742)], [HPE_MOVE], 20.0)

        # 439 x 4.81 = 2,111.59 MTM; IM +15% of that.
        assert cp1.exposure_change == pytest.approx(-2_111.59 + 316.7385, abs=0.01)
        assert cp3.exposure_change == pytest.approx(1_188.07 * 1.15, abs=0.01)
        assert cp7.exposure_change == pytest.approx(3_569.02 * 1.15, abs=0.01)
        # The CSA MTAs: CP-1 11,000; CP-3 19,000; CP-7 47,000 -- none clears.
        assert not is_material(cp1, 11_000)
        assert not is_material(cp3, 19_000)
        assert not is_material(cp7, 47_000)


class TestIsMaterial:
    @pytest.mark.parametrize(
        ("change", "mta", "expected"),
        [
            (11_000.01, 11_000.0, True),
            (11_000.0, 11_000.0, False),  # must *exceed* the MTA
            (10_999.99, 11_000.0, False),
            (-50_000.0, 11_000.0, False),  # a reduction never raises a call
            (0.01, 0.0, True),
            (0.0, 0.0, False),
        ],
    )
    def test_gate(self, change: float, mta: float, expected: bool) -> None:
        impact = EventImpact(tickers=["X"], mtm_change=change, im_change=0, exposure_change=change)

        assert is_material(impact, mta) is expected


class TestRationale:
    IMPACT = EventImpact(
        tickers=["HPE"], mtm_change=50_000.0, im_change=2_100.0, exposure_change=52_100.0
    )

    def test_money(self) -> None:
        assert money(1234567.891, "USD") == "USD 1,234,567.89"

    def test_event_sentence_states_the_move_and_the_impact(self) -> None:
        assert event_sentence(self.IMPACT, [HPE_MOVE], "USD") == (
            "The HPE move (USD 65.07 to USD 69.88) increased your exposure by USD 52,100.00"
        )

    def test_event_sentence_for_a_reduction(self) -> None:
        reduced = self.IMPACT.model_copy(update={"exposure_change": -1_795.0})

        assert "reduced your exposure by USD 1,795.00" in event_sentence(reduced, [HPE_MOVE], "USD")

    def test_event_sentence_names_several_moves(self) -> None:
        moves = [HPE_MOVE, PriceMove(ticker="MU", from_price=100, to_price=120)]
        both = self.IMPACT.model_copy(update={"tickers": ["HPE", "MU"]})

        assert event_sentence(both, moves, "USD").startswith(
            "The HPE and MU moves (USD 65.07 to USD 69.88; USD 100.00 to USD 120.00)"
        )

    def test_exposure_sentence_when_breached(self) -> None:
        text = exposure_sentence(1_000_000, 409_214.09, 340_000, 250_785.91, "USD", True)

        assert text == (
            "Your exposure of USD 1,000,000.00 exceeds the threshold of USD 340,000.00; "
            "after collateral held of USD 409,214.09, USD 250,785.91 is due."
        )

    def test_exposure_sentence_when_not_breached(self) -> None:
        text = exposure_sentence(100_000, 0, 340_000, 0, "USD", False)

        assert text.endswith(
            "is within the threshold of USD 340,000.00 and minimum transfer "
            "amount: no call is due."
        )

    def test_material_event_rationale(self) -> None:
        text = material_event_rationale(self.IMPACT, [HPE_MOVE], 11_000, "USD", "Tail.")

        assert text == (
            "The HPE move (USD 65.07 to USD 69.88) increased your exposure by USD 52,100.00, "
            "more than the minimum transfer amount of USD 11,000.00. Tail."
        )

    def test_below_materiality_rationale(self) -> None:
        small = self.IMPACT.model_copy(update={"exposure_change": 4_104.37})

        text = below_materiality_rationale(small, [HPE_MOVE], 47_000, "USD")

        assert text == (
            "The HPE move (USD 65.07 to USD 69.88) increased your exposure by USD 4,104.37, "
            "which does not exceed the minimum transfer amount of USD 47,000.00: no intraday "
            "call. A standing breach is called by the daily margin run."
        )


class TestPriceMove:
    def test_prices_must_be_positive(self) -> None:
        with pytest.raises(ValueError):
            PriceMove(ticker="HPE", from_price=0, to_price=69.88)
