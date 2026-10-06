"""The simulated historical book (MM-140): 1,000 synthetic counterparties and
~50,000 positions over the real S&P 500 universe. Warehouse only -- it never
enters Cloud SQL and never reaches an LLM; its CSA terms are structured data
drawn here, not documents.

Real-shaped, clearly synthetic:
- Names are "SIM <word> <suffix> <nnnn>" -- obviously not real firms.
- Types, jurisdictions and the standard/elite split follow the live seed
  (persistence.generators.counterparties); ratings are drawn per type.
- Thresholds and MTAs are drawn around the eight seeded CSAs
  (data/documents/csa: thresholds USD 90k-450k, MTAs USD 11k-47k), scaled by
  rating; rating triggers cut the threshold to 0 below B (or below BBB), and
  haircuts are the seeded ones (cash 0%, Treasuries 2%, corporates 8%, money
  market funds 1%).
- CSA terms are reviewed once a year (30% are renegotiated -> a new SCD2
  version) and ratings migrate one notch at quarterly reviews.
- Positions are sized by notional (USD 20k-250k, log-uniform; elite x1.5),
  75% long, quantity = notional / the ticker's first close in the window.

Deterministic: everything about counterparty i comes from its own seeded
generator, so the book is identical on every run (and on every chunk).
"""

from dataclasses import dataclass, field
from datetime import date

import numpy as np

from persistence.generators.counterparties import FINANCIAL_JURISDICTIONS, SUFFIXES_BY_TYPE
from persistence.models import (
    RATING_ORDER,
    AssetClass,
    CounterpartyTier,
    CounterpartyType,
    RatingGrade,
)

DEFAULT_SEED = 20261006
DEFAULT_COUNTERPARTIES = 1000
OPEN_END = date(9999, 12, 31)

TYPE_WEIGHTS = {
    CounterpartyType.BANK: 0.30,
    CounterpartyType.HEDGE_FUND: 0.45,
    CounterpartyType.ASSET_MANAGER: 0.25,
}
ELITE_SHARE = 0.15
RATING_WEIGHTS: dict[CounterpartyType, dict[RatingGrade, float]] = {
    CounterpartyType.BANK: {
        RatingGrade.AA: 0.20,
        RatingGrade.A: 0.45,
        RatingGrade.BBB: 0.30,
        RatingGrade.BB: 0.05,
    },
    CounterpartyType.HEDGE_FUND: {
        RatingGrade.A: 0.10,
        RatingGrade.BBB: 0.30,
        RatingGrade.BB: 0.35,
        RatingGrade.B: 0.20,
        RatingGrade.CCC: 0.05,
    },
    CounterpartyType.ASSET_MANAGER: {
        RatingGrade.AA: 0.10,
        RatingGrade.A: 0.40,
        RatingGrade.BBB: 0.40,
        RatingGrade.BB: 0.10,
    },
}
BASE_THRESHOLD: dict[RatingGrade, float] = {
    RatingGrade.AAA: 450_000,
    RatingGrade.AA: 400_000,
    RatingGrade.A: 300_000,
    RatingGrade.BBB: 200_000,
    RatingGrade.BB: 120_000,
    RatingGrade.B: 90_000,
    RatingGrade.CCC: 50_000,
}
ELITE_THRESHOLD_FACTOR = 1.25
MTA_RANGE = (10_000, 50_000)
HAIRCUTS = {"cash": 0.0, "treasury": 0.02, "corporate": 0.08, "mmf": 0.01}
ELIGIBLE_CHANCE = {"cash": 0.85, "treasury": 0.70, "corporate": 0.50, "mmf": 0.30}
RENEGOTIATION_CHANCE = 0.30
DOWNGRADE_CHANCE = 0.04
UPGRADE_CHANCE = 0.03
POSITIONS_RANGE = (35, 65)  # inclusive; mean 50
NOTIONAL_RANGE = (20_000.0, 250_000.0)
ELITE_NOTIONAL_FACTOR = 1.5
LONG_SHARE = 0.75
COLLATERAL_FACTOR_RANGE = (0.9, 1.2)
# Ratings migrate between AAA and CCC; D is a default, not a migration.
MIGRATION_GRADES = RATING_ORDER[:-1]
NAME_WORDS = (
    "Alder",
    "Aspen",
    "Basalt",
    "Birch",
    "Cedar",
    "Cobalt",
    "Copper",
    "Cypress",
    "Delta",
    "Ember",
    "Fjord",
    "Garnet",
    "Granite",
    "Harbor",
    "Hazel",
    "Heron",
    "Indigo",
    "Juniper",
    "Kestrel",
    "Larch",
    "Linden",
    "Maple",
    "Meadow",
    "Onyx",
    "Opal",
    "Orchid",
    "Pine",
    "Quarry",
    "Raven",
    "Ridge",
    "Rowan",
    "Sable",
    "Slate",
    "Spruce",
    "Summit",
    "Thistle",
    "Tundra",
    "Willow",
    "Yarrow",
    "Zephyr",
)


@dataclass(frozen=True)
class CsaVersion:
    version: int
    valid_from: date
    valid_to: date
    threshold: float
    mta: float
    trigger_below_grade: RatingGrade
    trigger_threshold: float
    haircuts: dict[str, float | None]
    change_reason: str
    currency: str = "USD"


@dataclass
class SimCounterparty:
    index: int
    id: str
    name: str
    type: CounterpartyType
    country: str
    tier: CounterpartyTier
    ratings: list[tuple[date, RatingGrade]]  # (effective from, grade), ascending
    csa_versions: list[CsaVersion]
    collateral_factor: float

    def rating_on(self, day: date) -> RatingGrade:
        current = self.ratings[0][1]
        for effective, grade in self.ratings:
            if effective <= day:
                current = grade
        return current

    def csa_on(self, day: date) -> CsaVersion:
        for version in self.csa_versions:
            if version.valid_from <= day <= version.valid_to:
                return version
        return (
            self.csa_versions[0] if day < self.csa_versions[0].valid_from else self.csa_versions[-1]
        )


@dataclass
class SimPosition:
    position_id: str
    counterparty_index: int
    ticker: str
    asset_class: AssetClass
    quantity: float


@dataclass
class SimulatedBook:
    counterparties: list[SimCounterparty]
    positions: list[SimPosition] = field(default_factory=list)


def _round_to(value: float, step: float) -> float:
    return float(max(step, round(value / step) * step))


def _pick(rng: np.random.Generator, weights: dict) -> object:
    keys = list(weights)
    probabilities = np.array([weights[k] for k in keys], dtype=float)
    return keys[int(rng.choice(len(keys), p=probabilities / probabilities.sum()))]


def _quarter_starts(start: date, end: date) -> list[date]:
    days: list[date] = []
    year, month = start.year, ((start.month - 1) // 3) * 3 + 1
    while True:
        month += 3
        if month > 12:
            year, month = year + 1, month - 12
        day = date(year, month, 1)
        if day > end:
            return days
        days.append(day)


def _ratings(
    rng: np.random.Generator, initial: RatingGrade, start: date, end: date
) -> list[tuple[date, RatingGrade]]:
    path = [(start, initial)]
    rank = MIGRATION_GRADES.index(initial)
    for review in _quarter_starts(start, end):
        draw = rng.random()
        if draw < DOWNGRADE_CHANCE and rank < len(MIGRATION_GRADES) - 1:
            rank += 1
        elif draw > 1 - UPGRADE_CHANCE and rank > 0:
            rank -= 1
        else:
            continue
        path.append((review, MIGRATION_GRADES[rank]))
    return path


def _csa_versions(
    rng: np.random.Generator,
    rating: RatingGrade,
    tier: CounterpartyTier,
    start: date,
    end: date,
) -> list[CsaVersion]:
    factor = ELITE_THRESHOLD_FACTOR if tier is CounterpartyTier.ELITE else 1.0
    threshold = _round_to(BASE_THRESHOLD[rating] * rng.uniform(0.6, 1.4) * factor, 5_000)
    mta = _round_to(rng.uniform(*MTA_RANGE), 1_000)
    trigger = RatingGrade.B if rng.random() < 0.75 else RatingGrade.BBB
    haircuts: dict[str, float | None] = {
        kind: (HAIRCUTS[kind] if rng.random() < ELIGIBLE_CHANCE[kind] else None)
        for kind in HAIRCUTS
    }
    if all(v is None for v in haircuts.values()):
        haircuts["cash"] = HAIRCUTS["cash"]
    review_month = int(rng.integers(1, 13))

    versions: list[CsaVersion] = []
    valid_from, reason = start, "initial"
    for year in range(start.year + 1, end.year + 1):
        review = date(year, review_month, 1)
        if review <= start or review > end or rng.random() >= RENEGOTIATION_CHANCE:
            continue
        versions.append(
            CsaVersion(
                len(versions) + 1,
                valid_from,
                date.fromordinal(review.toordinal() - 1),
                threshold,
                mta,
                trigger,
                0.0,
                dict(haircuts),
                reason,
            )
        )
        threshold = _round_to(threshold * rng.uniform(0.8, 1.25), 5_000)
        mta = _round_to(mta * rng.uniform(0.8, 1.25), 1_000)
        valid_from, reason = review, "renegotiated"
    versions.append(
        CsaVersion(
            len(versions) + 1,
            valid_from,
            OPEN_END,
            threshold,
            mta,
            trigger,
            0.0,
            dict(haircuts),
            reason,
        )
    )
    return versions


def generate_counterparty(index: int, seed: int, start: date, end: date) -> SimCounterparty:
    rng = np.random.default_rng([seed, index])
    cp_type = _pick(rng, TYPE_WEIGHTS)
    assert isinstance(cp_type, CounterpartyType)
    tier = CounterpartyTier.ELITE if rng.random() < ELITE_SHARE else CounterpartyTier.STANDARD
    rating = _pick(rng, RATING_WEIGHTS[cp_type])
    assert isinstance(rating, RatingGrade)
    word = NAME_WORDS[int(rng.integers(len(NAME_WORDS)))]
    suffixes = SUFFIXES_BY_TYPE[cp_type]
    suffix = suffixes[int(rng.integers(len(suffixes)))]
    return SimCounterparty(
        index=index,
        id=f"SIM-{index + 1:04d}",
        name=f"SIM {word} {suffix} {index + 1:04d}",
        type=cp_type,
        country=FINANCIAL_JURISDICTIONS[int(rng.integers(len(FINANCIAL_JURISDICTIONS)))],
        tier=tier,
        ratings=_ratings(rng, rating, start, end),
        csa_versions=_csa_versions(rng, rating, tier, start, end),
        collateral_factor=float(rng.uniform(*COLLATERAL_FACTOR_RANGE)),
    )


def generate_positions(
    counterparty: SimCounterparty, tickers: list[str], first_close: dict[str, float], seed: int
) -> list[SimPosition]:
    rng = np.random.default_rng([seed, counterparty.index, 1])
    count = int(rng.integers(POSITIONS_RANGE[0], POSITIONS_RANGE[1] + 1))
    chosen = rng.choice(len(tickers), size=min(count, len(tickers)), replace=False)
    scale = ELITE_NOTIONAL_FACTOR if counterparty.tier is CounterpartyTier.ELITE else 1.0
    low, high = np.log(NOTIONAL_RANGE[0]), np.log(NOTIONAL_RANGE[1])
    positions = []
    for n, j in enumerate(sorted(int(j) for j in chosen), start=1):
        ticker = tickers[j]
        notional = float(np.exp(rng.uniform(low, high))) * scale
        side = 1.0 if rng.random() < LONG_SHARE else -1.0
        quantity = side * max(1.0, float(round(notional / first_close[ticker])))
        positions.append(
            SimPosition(
                position_id=f"{counterparty.id}-P{n:03d}",
                counterparty_index=counterparty.index,
                ticker=ticker,
                asset_class=AssetClass.EQUITY,
                quantity=quantity,
            )
        )
    return positions


def generate_book(
    tickers: list[str],
    first_close: dict[str, float],
    start: date,
    end: date,
    seed: int = DEFAULT_SEED,
    count: int = DEFAULT_COUNTERPARTIES,
) -> SimulatedBook:
    """`tickers` are the priced S&P 500 symbols; `first_close` each one's
    first close in the window (positions are sized on it)."""
    priced = sorted(t for t in tickers if t in first_close)
    counterparties = [generate_counterparty(i, seed, start, end) for i in range(count)]
    positions = [
        p for cp in counterparties for p in generate_positions(cp, priced, first_close, seed)
    ]
    return SimulatedBook(counterparties=counterparties, positions=positions)
