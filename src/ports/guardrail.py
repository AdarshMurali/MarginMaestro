"""Guardrails around every LLM call (MM-113, ADR-0014).

Two implementations: Model Armor on GCP (MM-114, the screening engine Agent
Platform uses) and an in-code baseline that is also the post-trial fallback
(ADR-0017). Both screen the text going to the model and the text coming back.
"""

from typing import Literal, Protocol

from pydantic import BaseModel

Stage = Literal["prompt", "response"]


class Verdict(BaseModel):
    allowed: bool
    guardrail: str  # which implementation decided, e.g. "incode", "modelarmor"
    reasons: list[str] = []


class GuardrailError(Exception):
    """Base for guardrail outcomes that stop an LLM call. Callers treat it like
    any other failure to get an answer: the margin call is held, not sent."""


class GuardrailBlocked(GuardrailError):
    """The text was screened and rejected (e.g. a prompt-injection attempt)."""

    def __init__(self, stage: Stage, verdict: Verdict) -> None:
        self.stage = stage
        self.verdict = verdict
        super().__init__(f"{verdict.guardrail} blocked the {stage}: {', '.join(verdict.reasons)}")


class GuardrailUnavailable(GuardrailError):
    """The text could not be screened. Fail closed: never call the model (or
    use its answer) unscreened."""


class Guardrail(Protocol):
    name: str

    def screen(self, text: str, stage: Stage) -> Verdict:
        """Raise GuardrailUnavailable if screening itself fails."""
        ...
