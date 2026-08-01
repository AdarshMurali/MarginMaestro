import pytest

from calc.collateral_optimizer import InventoryItem, optimize_collateral


class TestOptimizeCollateral:
    def test_zero_required_amount_needs_no_collateral(self) -> None:
        result = optimize_collateral(
            0.0,
            ["cash"],
            {"cash": 0.0},
            [InventoryItem(collateral_type="cash", available_value_usd=1000.0)],
        )

        assert result.proposed_collateral == []
        assert result.post_haircut_value == 0.0
        assert result.fully_funded is True

    def test_single_type_fully_covers_the_requirement(self) -> None:
        inventory = [InventoryItem(collateral_type="cash", available_value_usd=200_000.0)]

        result = optimize_collateral(100_000.0, ["cash"], {"cash": 0.0}, inventory)

        assert result.fully_funded is True
        assert len(result.proposed_collateral) == 1
        assert result.proposed_collateral[0].value_usd == pytest.approx(100_000.0)
        assert result.post_haircut_value == pytest.approx(100_000.0)

    def test_prefers_lowest_haircut_first(self) -> None:
        inventory = [
            InventoryItem(collateral_type="security", available_value_usd=200_000.0),
            InventoryItem(collateral_type="cash", available_value_usd=50_000.0),
        ]
        haircuts = {"cash": 0.0, "security": 0.1}

        result = optimize_collateral(100_000.0, ["cash", "security"], haircuts, inventory)

        assert result.fully_funded is True
        assert result.proposed_collateral[0].collateral_type == "cash"
        assert result.proposed_collateral[0].value_usd == pytest.approx(50_000.0)
        assert result.proposed_collateral[0].post_haircut_value == pytest.approx(50_000.0)
        assert result.proposed_collateral[1].collateral_type == "security"
        assert result.proposed_collateral[1].post_haircut_value == pytest.approx(50_000.0)
        assert result.post_haircut_value == pytest.approx(100_000.0)

    def test_insufficient_inventory_is_not_fully_funded(self) -> None:
        inventory = [InventoryItem(collateral_type="cash", available_value_usd=30_000.0)]

        result = optimize_collateral(100_000.0, ["cash"], {"cash": 0.0}, inventory)

        assert result.fully_funded is False
        assert result.post_haircut_value == pytest.approx(30_000.0)
        assert result.proposed_collateral[0].value_usd == pytest.approx(30_000.0)

    def test_ineligible_inventory_is_excluded(self) -> None:
        inventory = [
            InventoryItem(collateral_type="crypto", available_value_usd=1_000_000.0),
            InventoryItem(collateral_type="cash", available_value_usd=50_000.0),
        ]

        result = optimize_collateral(50_000.0, ["cash"], {"cash": 0.0}, inventory)

        assert len(result.proposed_collateral) == 1
        assert result.proposed_collateral[0].collateral_type == "cash"

    def test_full_haircut_collateral_is_skipped(self) -> None:
        inventory = [
            InventoryItem(collateral_type="worthless", available_value_usd=1_000_000.0),
            InventoryItem(collateral_type="cash", available_value_usd=50_000.0),
        ]
        haircuts = {"worthless": 1.0, "cash": 0.0}

        result = optimize_collateral(50_000.0, ["worthless", "cash"], haircuts, inventory)

        assert len(result.proposed_collateral) == 1
        assert result.proposed_collateral[0].collateral_type == "cash"

    def test_zero_available_inventory_item_is_skipped(self) -> None:
        inventory = [
            InventoryItem(collateral_type="cash", available_value_usd=0.0),
            InventoryItem(collateral_type="security", available_value_usd=50_000.0),
        ]
        haircuts = {"cash": 0.0, "security": 0.1}

        result = optimize_collateral(10_000.0, ["cash", "security"], haircuts, inventory)

        assert len(result.proposed_collateral) == 1
        assert result.proposed_collateral[0].collateral_type == "security"

    def test_no_eligible_inventory_returns_empty_with_explanatory_rationale(self) -> None:
        result = optimize_collateral(50_000.0, ["cash"], {"cash": 0.0}, [])

        assert result.proposed_collateral == []
        assert result.fully_funded is False
        assert "No eligible inventory" in result.rationale
