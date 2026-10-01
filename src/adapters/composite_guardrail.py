"""Defence in depth (MM-114): run several guardrails on the same text; any
block wins, and any outage fails the whole screening closed. Used to pair
Model Armor with the in-code checks -- live testing showed Model Armor (at
medium sensitivity) let a subtle "pretend the CSA says ... disregard prior
guidance" prompt through, which the in-code patterns catch.
"""

from collections.abc import Sequence

from ports.guardrail import Guardrail, Stage, Verdict


class CompositeGuardrail:
    def __init__(self, guardrails: Sequence[Guardrail]) -> None:
        if not guardrails:
            raise ValueError("CompositeGuardrail needs at least one guardrail")
        self._guardrails = list(guardrails)
        self.name = "+".join(g.name for g in self._guardrails)

    def screen(self, text: str, stage: Stage) -> Verdict:
        # Every guardrail runs (no short-circuit) so the verdict lists every
        # reason; an exception from any of them propagates -> fail closed.
        verdicts = [g.screen(text, stage) for g in self._guardrails]
        blocked = [v for v in verdicts if not v.allowed]
        if not blocked:
            return Verdict(allowed=True, guardrail=self.name)
        return Verdict(
            allowed=False,
            guardrail="+".join(v.guardrail for v in blocked),
            reasons=[reason for v in blocked for reason in v.reasons],
        )
