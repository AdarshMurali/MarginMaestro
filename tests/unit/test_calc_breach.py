from calc.breach import evaluate_breach
from calc.models import CSATerms


def _csa(threshold: float = 75000.0, mta: float = 10000.0) -> CSATerms:
    return CSATerms(threshold=threshold, mta=mta)


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
