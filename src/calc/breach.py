from calc.models import BreachResult, CSATerms


def evaluate_breach(exposure: float, collateral_held: float, csa_terms: CSATerms) -> BreachResult:
    """Standard CSA margin-call mechanics.

    required_support = max(0, exposure - threshold): the credit support the
    CSA entitles the counterparty to demand once exposure exceeds threshold.
    delivery_amount = required_support - collateral already held. A call is
    only triggered if there's an actual shortfall (delivery_amount > 0) that
    clears the MTA materiality gate. Call direction only -- returning excess
    collateral when over-collateralized is out of scope.
    """
    required_support = max(0.0, exposure - csa_terms.threshold)
    delivery_amount = required_support - collateral_held

    if delivery_amount > 0 and delivery_amount >= csa_terms.mta:
        return BreachResult(breached=True, call_amount=delivery_amount)
    return BreachResult(breached=False, call_amount=0.0)
