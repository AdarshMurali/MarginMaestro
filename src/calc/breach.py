from calc.models import BreachResult, CSATerms
from persistence.models import RATING_ORDER, RatingGrade


def effective_threshold(csa_terms: CSATerms, current_rating: RatingGrade | None) -> float:
    """Applies any CSA rating-trigger clause whose grade the counterparty's
    current rating has fallen below. Deterministic clause application
    (CLAUDE.md golden rule 1) -- the LLM already extracted what each clause
    says (csa_rag.py); this just compares two known grades and, if multiple
    triggers fire at once, takes the most restrictive (lowest) threshold.
    """
    if current_rating is None or not csa_terms.rating_triggers:
        return csa_terms.threshold

    current_rank = RATING_ORDER.index(current_rating)
    fired = [
        t.reduced_threshold
        for t in csa_terms.rating_triggers
        if current_rank > RATING_ORDER.index(t.below_grade)
    ]
    if not fired:
        return csa_terms.threshold
    return min(fired)


def evaluate_breach(
    exposure: float,
    collateral_held: float,
    csa_terms: CSATerms,
    current_rating: RatingGrade | None = None,
) -> BreachResult:
    """Standard CSA margin-call mechanics.

    required_support = max(0, exposure - threshold): the credit support the
    CSA entitles the counterparty to demand once exposure exceeds threshold.
    delivery_amount = required_support - collateral already held. A call is
    only triggered if there's an actual shortfall (delivery_amount > 0) that
    clears the MTA materiality gate. Call direction only -- returning excess
    collateral when over-collateralized is out of scope.

    `threshold` is CSATerms.threshold, unless a rating-trigger clause has
    fired for the counterparty's `current_rating`, in which case the
    clause's reduced threshold applies instead (see effective_threshold).
    """
    threshold = effective_threshold(csa_terms, current_rating)
    required_support = max(0.0, exposure - threshold)
    delivery_amount = required_support - collateral_held

    if delivery_amount > 0 and delivery_amount >= csa_terms.mta:
        return BreachResult(breached=True, call_amount=delivery_amount)
    return BreachResult(breached=False, call_amount=0.0)
