from calc.breach import effective_threshold, evaluate_breach
from calc.models import CSATerms
from persistence.models import RatingGrade, RatingTrigger


def _csa(
    threshold: float = 75000.0,
    mta: float = 10000.0,
    rating_triggers: list[RatingTrigger] | None = None,
) -> CSATerms:
    return CSATerms(threshold=threshold, mta=mta, rating_triggers=rating_triggers or [])


class TestEvaluateBreach:
    def test_no_breach_when_exposure_well_below_threshold(self) -> None:
        result = evaluate_breach(exposure=50000.0, collateral_held=0.0, csa_terms=_csa())

        assert result.breached is False
        assert result.call_amount == 0.0

    def test_no_breach_at_exact_threshold(self) -> None:
        # Hand-computed: required_support = max(0, 75000-75000) = 0; delivery = 0
        result = evaluate_breach(exposure=75000.0, collateral_held=0.0, csa_terms=_csa())

        assert result.breached is False
        assert result.call_amount == 0.0

    def test_no_call_when_shortfall_is_below_mta(self) -> None:
        # required_support = 80000-75000 = 5000; delivery = 5000-0 = 5000 < mta(10000)
        result = evaluate_breach(exposure=80000.0, collateral_held=0.0, csa_terms=_csa())

        assert result.breached is False
        assert result.call_amount == 0.0

    def test_breach_when_shortfall_clears_mta(self) -> None:
        # required_support = 100000-75000 = 25000; delivery = 25000 >= mta(10000)
        result = evaluate_breach(exposure=100000.0, collateral_held=0.0, csa_terms=_csa())

        assert result.breached is True
        assert result.call_amount == 25000.0

    def test_existing_collateral_reduces_the_call_amount(self) -> None:
        # required_support = 25000; delivery = 25000-20000 = 5000 < mta(10000) -> no call
        result = evaluate_breach(exposure=100000.0, collateral_held=20000.0, csa_terms=_csa())

        assert result.breached is False
        assert result.call_amount == 0.0

    def test_large_shortfall_partially_offset_by_collateral_still_breaches(self) -> None:
        # required_support = 25000; delivery = 25000-5000 = 20000 >= mta(10000)
        result = evaluate_breach(exposure=100000.0, collateral_held=5000.0, csa_terms=_csa())

        assert result.breached is True
        assert result.call_amount == 20000.0

    def test_over_collateralized_never_produces_a_negative_call(self) -> None:
        # required_support = 25000; delivery = 25000-40000 = -15000 -> no breach
        result = evaluate_breach(exposure=100000.0, collateral_held=40000.0, csa_terms=_csa())

        assert result.breached is False
        assert result.call_amount == 0.0

    def test_zero_threshold_and_mta_still_requires_a_positive_shortfall(self) -> None:
        result = evaluate_breach(
            exposure=0.0, collateral_held=0.0, csa_terms=_csa(threshold=0.0, mta=0.0)
        )

        assert result.breached is False
        assert result.call_amount == 0.0

    def test_rating_trigger_ignored_when_current_rating_not_below_grade(self) -> None:
        # AA is not below BBB -- trigger doesn't fire, flat threshold (75000) applies.
        csa = _csa(
            rating_triggers=[RatingTrigger(below_grade=RatingGrade.BBB, reduced_threshold=0.0)]
        )
        result = evaluate_breach(
            exposure=50000.0, collateral_held=0.0, csa_terms=csa, current_rating=RatingGrade.AA
        )

        assert result.breached is False
        assert result.call_amount == 0.0

    def test_rating_trigger_fires_and_reduces_threshold(self) -> None:
        # BB is below BBB -- trigger fires, threshold drops to 0, full exposure is callable.
        csa = _csa(
            threshold=75000.0,
            mta=10000.0,
            rating_triggers=[RatingTrigger(below_grade=RatingGrade.BBB, reduced_threshold=0.0)],
        )
        result = evaluate_breach(
            exposure=50000.0, collateral_held=0.0, csa_terms=csa, current_rating=RatingGrade.BB
        )

        assert result.breached is True
        assert result.call_amount == 50000.0

    def test_no_current_rating_leaves_flat_threshold_unchanged(self) -> None:
        csa = _csa(
            rating_triggers=[RatingTrigger(below_grade=RatingGrade.BBB, reduced_threshold=0.0)]
        )
        result = evaluate_breach(
            exposure=50000.0, collateral_held=0.0, csa_terms=csa, current_rating=None
        )

        assert result.breached is False
        assert result.call_amount == 0.0

    def test_multiple_fired_triggers_take_the_most_restrictive_threshold(self) -> None:
        csa = _csa(
            threshold=75000.0,
            rating_triggers=[
                RatingTrigger(below_grade=RatingGrade.A, reduced_threshold=30000.0),
                RatingTrigger(below_grade=RatingGrade.BB, reduced_threshold=0.0),
            ],
        )
        # CCC is below both A and BB -- both fire, min(30000, 0) = 0 applies.
        assert effective_threshold(csa, RatingGrade.CCC) == 0.0
        # BBB is below A but not below BB -- only the 30000 trigger fires.
        assert effective_threshold(csa, RatingGrade.BBB) == 30000.0
        # AA is below neither -- flat threshold applies.
        assert effective_threshold(csa, RatingGrade.AA) == 75000.0
