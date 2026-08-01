"""Collateral Optimizer (MM-48, docs/AGENTS.md #5): selects cheapest-to-
deliver collateral from available inventory to meet a required amount,
respecting eligibility and haircuts. Deterministic (a greedy solver, per
AGENTS.md's "LP/greedy for the demo" note) -- the LLM never chooses
collateral; narration here is plain code, not an LLM call, since the
choice itself is fully explained by the numbers (AGENTS.md's LLM
narration is explicitly optional). Placed in calc/, not agents/, matching
the Calculation Agent's own precedent: AGENTS.md's Type line for this
responsibility is "code", same category. Standalone tool this phase --
not auto-invoked mid-lifecycle (confirmed with the user before MM-46
started).

"Cheapest to deliver" here means lowest haircut first: a lower haircut
returns more post-haircut credit per dollar of raw value posted, so it
uses up less of the available inventory for the same credit -- balance-
sheet cost (the fuller "cheapest" definition) is explicitly deferred per
AGENTS.md's Notes line, since no cost-of-funds/yield data exists anywhere
in this project yet."""

from pydantic import BaseModel

CREDIT_EPSILON = 1e-6


class InventoryItem(BaseModel):
    collateral_type: str
    available_value_usd: float


class ProposedCollateral(BaseModel):
    collateral_type: str
    value_usd: float
    haircut_pct: float
    post_haircut_value: float


class OptimizationResult(BaseModel):
    proposed_collateral: list[ProposedCollateral]
    post_haircut_value: float
    fully_funded: bool
    rationale: str


def _build_rationale(
    proposed: list[ProposedCollateral], required_amount: float, fully_funded: bool
) -> str:
    if not proposed:
        return f"No eligible inventory available to meet the required {required_amount:,.2f}."
    lines = [
        f"{p.value_usd:,.2f} of {p.collateral_type} (haircut {p.haircut_pct:.1%}) "
        f"-> {p.post_haircut_value:,.2f} credit"
        for p in proposed
    ]
    summary = "; ".join(lines)
    if fully_funded:
        return f"Selected lowest-haircut eligible collateral first: {summary}."
    return f"Selected all available eligible collateral (insufficient to fully fund): {summary}."


def optimize_collateral(
    required_amount: float,
    eligible_collateral: list[str],
    haircuts: dict[str, float],
    inventory: list[InventoryItem],
) -> OptimizationResult:
    if required_amount <= 0:
        return OptimizationResult(
            proposed_collateral=[],
            post_haircut_value=0.0,
            fully_funded=True,
            rationale="No collateral required.",
        )

    eligible_inventory = [item for item in inventory if item.collateral_type in eligible_collateral]
    ranked = sorted(eligible_inventory, key=lambda item: haircuts.get(item.collateral_type, 1.0))

    proposed: list[ProposedCollateral] = []
    remaining = required_amount
    for item in ranked:
        if remaining <= CREDIT_EPSILON:
            break
        haircut = haircuts.get(item.collateral_type, 0.0)
        credit_rate = 1 - haircut
        if credit_rate <= 0 or item.available_value_usd <= 0:
            continue

        raw_needed = remaining / credit_rate
        raw_used = min(item.available_value_usd, raw_needed)
        credit = raw_used * credit_rate

        proposed.append(
            ProposedCollateral(
                collateral_type=item.collateral_type,
                value_usd=raw_used,
                haircut_pct=haircut,
                post_haircut_value=credit,
            )
        )
        remaining -= credit

    total_credit = sum(p.post_haircut_value for p in proposed)
    fully_funded = remaining <= CREDIT_EPSILON
    return OptimizationResult(
        proposed_collateral=proposed,
        post_haircut_value=total_credit,
        fully_funded=fully_funded,
        rationale=_build_rationale(proposed, required_amount, fully_funded),
    )
