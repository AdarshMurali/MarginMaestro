import argparse
import json
import random
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from persistence.generators.collateral import generate_collateral
from persistence.generators.counterparties import generate_counterparties
from persistence.generators.portfolios import generate_portfolios_and_positions
from persistence.generators.ratings import generate_ratings

GENERATOR_VERSION = "1.0.0"
DEFAULT_SEED = 42
DEFAULT_OUTPUT_DIR = Path("data/generated")


def generate_all(seed: int = DEFAULT_SEED, as_of: date | None = None) -> dict[str, list[BaseModel]]:
    as_of = as_of or datetime.now(UTC).date()
    rng = random.Random(seed)

    counterparties = generate_counterparties(seed)
    counterparty_ids = [cp.id for cp in counterparties]

    portfolios, positions = generate_portfolios_and_positions(rng, counterparty_ids, as_of)
    ratings = generate_ratings(rng, counterparty_ids, as_of)
    collateral = generate_collateral(rng, counterparty_ids)

    return {
        "counterparties": list(counterparties),
        "portfolios": list(portfolios),
        "positions": list(positions),
        "ratings": list(ratings),
        "collateral": list(collateral),
    }


def _safe_join(base_dir: Path, filename: str) -> Path:
    """Resolve filename under base_dir, refusing to write outside it."""
    base_resolved = base_dir.resolve()
    target = (base_resolved / filename).resolve()
    if not target.is_relative_to(base_resolved):
        raise ValueError(f"Refusing to write outside {base_resolved}: {target}")
    return target


def _write_json(path: Path, records: list[BaseModel], seed: int, as_of: date) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "version": GENERATOR_VERSION,
        "seed": seed,
        "as_of": as_of.isoformat(),
        "generated_at": datetime.now(UTC).isoformat(),
        "count": len(records),
        "records": [record.model_dump(mode="json") for record in records],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_all(
    seed: int = DEFAULT_SEED,
    as_of: date | None = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> None:
    as_of = as_of or datetime.now(UTC).date()
    data = generate_all(seed, as_of)
    for name, records in data.items():
        target = _safe_join(output_dir, f"{name}.json")
        _write_json(target, records, seed, as_of)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate MarginMaestro synthetic data")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    write_all(seed=args.seed, output_dir=args.output_dir)


if __name__ == "__main__":
    main()
