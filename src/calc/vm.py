from calc.models import PortfolioMTM, PricingError, VariationMargin


def compute_variation_margin(mtm_today: PortfolioMTM, mtm_prior: PortfolioMTM) -> VariationMargin:
    """Variation Margin: the change in mark-to-market since the last exchange.

    Takes two already-computed compute_mtm() snapshots (today vs. the prior
    exchange, e.g. sourced from two price_history dates) rather than raw
    prices, so it composes directly on MM-17's output.
    """
    if mtm_today.portfolio_id != mtm_prior.portfolio_id:
        raise PricingError(
            "compute_variation_margin requires both snapshots to be for the same "
            f"portfolio; got '{mtm_today.portfolio_id}' and '{mtm_prior.portfolio_id}'"
        )

    return VariationMargin(
        portfolio_id=mtm_today.portfolio_id,
        mtm_today=mtm_today.total_mtm,
        mtm_prior=mtm_prior.total_mtm,
        variation_margin=mtm_today.total_mtm - mtm_prior.total_mtm,
    )
