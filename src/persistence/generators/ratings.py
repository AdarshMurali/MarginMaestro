import random
from datetime import date

from persistence.models import Rating, RatingGrade

# "D" (default) is intentionally excluded from initial generation -- it's a
# downgrade outcome for the Phase 4 simulator to drive counterparties into,
# not a plausible starting state.
INITIAL_RATING_GRADES = [
    RatingGrade.AAA,
    RatingGrade.AA,
    RatingGrade.A,
    RatingGrade.BBB,
    RatingGrade.BB,
    RatingGrade.B,
    RatingGrade.CCC,
]


def generate_ratings(rng: random.Random, counterparty_ids: list[str], as_of: date) -> list[Rating]:
    ratings: list[Rating] = []
    for i, cp_id in enumerate(counterparty_ids, start=1):
        ratings.append(
            Rating(
                id=f"RTG-{i}",
                counterparty_id=cp_id,
                grade=rng.choice(INITIAL_RATING_GRADES),
                rating_date=as_of,
            )
        )
    return ratings
