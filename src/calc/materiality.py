"""Intraday materiality gate and call rationale (MM-125, Phase G5b).

An intraday market event raises a margin call only if *its own* impact on a
counterparty's exposure exceeds the CSA minimum transfer amount. Found live on
2026-10-02: HPE's +7.4% move re-checked every HPE holder's whole book and
raised calls for breaches that already existed, although HPE moved those
exposures by only a few thousand dollars. Standing breaches are the daily
margin run's job.

Deterministic (CLAUDE.md golden rule 1, ADR-0005): the impact uses the same
exposure math as the breach check -- exposure = variation margin + initial
margin -- restricted to the positions in the moved tickers, priced before and
after the move. The rationale is plain code too: every figure in it comes from
the calculation, never from the LLM.
"""

from calc.im import compute_initial_margin
from calc.models import EventImpact, PriceMove
from calc.mtm import compute_mtm
from persistence.models import Position


def event_exposure_impact(
    positions: list[Position], moves: list[PriceMove], vix_level: float
) -> EventImpact:
    """Change in exposure caused by `moves` alone, over one portfolio.

    VM = MTM today - MTM at the prior close, and the prior-close MTM doesn't
    move intraday, so the VM change is the MTM change: quantity x (to - from)
    per moved position. IM is additive per position (|MTM| x risk weight x
    VIX multiplier), so its change is computed over the same positions. A
    counterparty that holds none of the moved tickers has zero impact."""
    to_prices = {m.ticker: m.to_price for m in moves}
    from_prices = {m.ticker: m.from_price for m in moves}
    affected = [p for p in positions if p.ticker in to_prices]
    tickers = sorted({p.ticker for p in affected})
    if not affected:
        return EventImpact(tickers=[], mtm_change=0.0, im_change=0.0, exposure_change=0.0)

    before = compute_mtm(affected, from_prices)
    after = compute_mtm(affected, to_prices)
    mtm_change = after.total_mtm - before.total_mtm
    im_change = (
        compute_initial_margin(after, vix_level).initial_margin
        - compute_initial_margin(before, vix_level).initial_margin
    )
    return EventImpact(
        tickers=tickers,
        mtm_change=mtm_change,
        im_change=im_change,
        exposure_change=mtm_change + im_change,
    )


def is_material(impact: EventImpact, mta: float) -> bool:
    """The gate: the event must *increase* exposure by more than the MTA. A
    move that reduces exposure never raises a call, however large."""
    return impact.exposure_change > mta


def money(amount: float, currency: str) -> str:
    return f"{currency} {amount:,.2f}"


def _move_text(impact: EventImpact, moves: list[PriceMove], currency: str) -> str:
    moved = [m for m in moves if m.ticker in impact.tickers] or moves
    names = " and ".join(m.ticker for m in moved)
    prices = "; ".join(
        f"{money(m.from_price, currency)} to {money(m.to_price, currency)}" for m in moved
    )
    noun = "move" if len(moved) == 1 else "moves"
    return f"The {names} {noun} ({prices})"


def event_sentence(impact: EventImpact, moves: list[PriceMove], currency: str) -> str:
    verb = "increased" if impact.exposure_change >= 0 else "reduced"
    return (
        f"{_move_text(impact, moves, currency)} {verb} your exposure by "
        f"{money(abs(impact.exposure_change), currency)}"
    )


def exposure_sentence(
    exposure: float,
    collateral_held: float,
    threshold: float,
    call_amount: float,
    currency: str,
    breached: bool,
) -> str:
    if not breached:
        return (
            f"Your exposure of {money(exposure, currency)}, with collateral held of "
            f"{money(collateral_held, currency)}, is within the threshold of "
            f"{money(threshold, currency)} and minimum transfer amount: no call is due."
        )
    return (
        f"Your exposure of {money(exposure, currency)} exceeds the threshold of "
        f"{money(threshold, currency)}; after collateral held of "
        f"{money(collateral_held, currency)}, {money(call_amount, currency)} is due."
    )


def material_event_rationale(
    impact: EventImpact, moves: list[PriceMove], mta: float, currency: str, exposure_text: str
) -> str:
    return (
        f"{event_sentence(impact, moves, currency)}, more than the minimum transfer amount "
        f"of {money(mta, currency)}. {exposure_text}"
    )


def below_materiality_rationale(
    impact: EventImpact, moves: list[PriceMove], mta: float, currency: str
) -> str:
    return (
        f"{event_sentence(impact, moves, currency)}, which does not exceed the minimum "
        f"transfer amount of {money(mta, currency)}: no intraday call. A standing breach "
        "is called by the daily margin run."
    )
