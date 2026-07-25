import json
import random
from datetime import date

import pytest

from config.settings import get_settings
from persistence.generators.collateral import generate_collateral
from persistence.generators.counterparties import generate_counterparties
from persistence.generators.portfolios import (
    MAX_POSITIONS_PER_PORTFOLIO,
    MIN_POSITIONS_PER_PORTFOLIO,
    generate_portfolios_and_positions,
)
from persistence.generators.ratings import generate_ratings
from persistence.generators.run import _safe_join, generate_all, write_all
from persistence.models import RatingGrade

SEED = 42
AS_OF = date(2026, 1, 1)


def test_counterparties_deterministic_and_counted() -> None:
    first = generate_counterparties(SEED)
    second = generate_counterparties(SEED)
    assert first == second
    assert len(first) == 8
    assert [cp.id for cp in first] == [f"CP-{i}" for i in range(1, 9)]


def test_portfolios_and_positions_counts_and_tickers() -> None:
    counterparty_ids = [f"CP-{i}" for i in range(1, 9)]
    rng = random.Random(SEED)
    portfolios, positions = generate_portfolios_and_positions(rng, counterparty_ids, AS_OF)

    assert len(portfolios) == 8
    assert [p.id for p in portfolios] == [f"PF-{i}" for i in range(1, 9)]

    universe = set(get_settings().market_universe_list)
    positions_per_portfolio: dict[str, int] = {}
    for position in positions:
        assert position.ticker in universe
        assert position.quantity != 0
        positions_per_portfolio[position.portfolio_id] = (
            positions_per_portfolio.get(position.portfolio_id, 0) + 1
        )

    for count in positions_per_portfolio.values():
        assert MIN_POSITIONS_PER_PORTFOLIO <= count <= MAX_POSITIONS_PER_PORTFOLIO


def test_ratings_excludes_default_grade() -> None:
    counterparty_ids = [f"CP-{i}" for i in range(1, 9)]
    rng = random.Random(SEED)
    ratings = generate_ratings(rng, counterparty_ids, AS_OF)

    assert len(ratings) == 8
    assert all(rating.grade != RatingGrade.D for rating in ratings)


def test_collateral_has_at_least_one_cash_item_per_counterparty() -> None:
    counterparty_ids = [f"CP-{i}" for i in range(1, 9)]
    rng = random.Random(SEED)
    items = generate_collateral(rng, counterparty_ids)

    from persistence.models import CollateralType

    cash_counterparties = {
        item.counterparty_id for item in items if item.collateral_type == CollateralType.CASH
    }
    assert cash_counterparties == set(counterparty_ids)


def test_generate_all_is_fully_deterministic_for_same_seed() -> None:
    first = generate_all(seed=SEED, as_of=AS_OF)
    second = generate_all(seed=SEED, as_of=AS_OF)

    for key in first:
        assert first[key] == second[key]


def test_generate_all_differs_for_different_seed() -> None:
    first = generate_all(seed=SEED, as_of=AS_OF)
    second = generate_all(seed=SEED + 1, as_of=AS_OF)

    assert first["counterparties"] != second["counterparties"]


def test_write_all_produces_valid_json_files(tmp_path) -> None:
    write_all(seed=SEED, as_of=AS_OF, output_dir=tmp_path)

    for name, expected_count_range in [
        ("counterparties", (8, 8)),
        ("portfolios", (8, 8)),
        ("ratings", (8, 8)),
        ("collateral", (8, 24)),
    ]:
        path = tmp_path / f"{name}.json"
        assert path.exists()
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["seed"] == SEED
        assert payload["as_of"] == AS_OF.isoformat()
        low, high = expected_count_range
        assert low <= payload["count"] <= high
        assert len(payload["records"]) == payload["count"]


def test_safe_join_allows_normal_filenames(tmp_path) -> None:
    result = _safe_join(tmp_path, "counterparties.json")
    assert result == (tmp_path / "counterparties.json").resolve()


def test_safe_join_rejects_path_traversal(tmp_path) -> None:
    with pytest.raises(ValueError, match="Refusing to write outside"):
        _safe_join(tmp_path, "../../etc/passwd")
