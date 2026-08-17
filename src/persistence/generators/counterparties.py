from faker import Faker

from persistence.models import Counterparty, CounterpartyTier, CounterpartyType

# Fixed, curated subset marked elite (golden rule #7: curated demo universe,
# not a random pick) -- deliberately not drawn from `fake`'s rng so it can't
# perturb the existing deterministic name/type/country sequence per seed.
ELITE_COUNTERPARTY_IDS = {"CP-1", "CP-5"}

SUFFIXES_BY_TYPE = {
    CounterpartyType.BANK: ["Bank", "Bank Corp", "Financial"],
    CounterpartyType.HEDGE_FUND: ["Capital", "Partners", "Fund Management"],
    CounterpartyType.ASSET_MANAGER: ["Asset Management", "Capital Management", "Partners"],
}

# Major financial-center jurisdictions -- realistic for margin-call
# counterparties, unlike Faker's uniform-over-all-countries default.
FINANCIAL_JURISDICTIONS = [
    "United States",
    "United Kingdom",
    "Germany",
    "France",
    "Switzerland",
    "Japan",
    "Singapore",
    "Hong Kong",
    "Cayman Islands",
    "Luxembourg",
    "Ireland",
    "Canada",
    "Australia",
]


def generate_counterparties(seed: int, count: int = 8) -> list[Counterparty]:
    fake = Faker()
    fake.seed_instance(seed)

    counterparties: list[Counterparty] = []
    for i in range(1, count + 1):
        cp_id = f"CP-{i}"
        cp_type = fake.random_element(list(SUFFIXES_BY_TYPE))
        name = f"{fake.last_name()} {fake.random_element(SUFFIXES_BY_TYPE[cp_type])}"
        counterparties.append(
            Counterparty(
                id=cp_id,
                name=name,
                type=cp_type,
                country=fake.random_element(FINANCIAL_JURISDICTIONS),
                tier=(
                    CounterpartyTier.ELITE
                    if cp_id in ELITE_COUNTERPARTY_IDS
                    else CounterpartyTier.STANDARD
                ),
            )
        )
    return counterparties
