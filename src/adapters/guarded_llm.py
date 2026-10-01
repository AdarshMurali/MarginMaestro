"""`LLMClient` that screens every call (MM-113, ADR-0014): user prompt (which
carries retrieved RAG chunks and any client text) before the model, the
model's answer after. Fails closed: a blocked or unscreenable call raises, so
the margin call is held rather than sent on unscreened text. Every verdict is
logged and counted (marginmaestro_guardrail_verdicts_total).

The system prompt is ours, so it isn't screened.
"""

from typing import TypeVar

import structlog
from pydantic import BaseModel

from observability.metrics import GUARDRAIL_VERDICTS_TOTAL
from ports.guardrail import (
    Guardrail,
    GuardrailBlocked,
    GuardrailUnavailable,
    Stage,
)
from ports.llm import LLMClient

T = TypeVar("T", bound=BaseModel)
logger = structlog.get_logger(__name__)


class GuardedLLM:
    def __init__(self, llm: LLMClient, guardrail: Guardrail) -> None:
        self._llm = llm
        self._guardrail = guardrail

    def _check(self, text: str, stage: Stage) -> None:
        try:
            verdict = self._guardrail.screen(text, stage)
        except GuardrailUnavailable:
            GUARDRAIL_VERDICTS_TOTAL.labels(self._guardrail.name, stage, "unavailable").inc()
            logger.error("guardrail_unavailable", guardrail=self._guardrail.name, stage=stage)
            raise
        except Exception as exc:  # any screening failure is an outage: fail closed
            GUARDRAIL_VERDICTS_TOTAL.labels(self._guardrail.name, stage, "unavailable").inc()
            logger.error(
                "guardrail_unavailable", guardrail=self._guardrail.name, stage=stage, error=str(exc)
            )
            raise GuardrailUnavailable(
                f"{self._guardrail.name} could not screen the {stage}"
            ) from exc
        outcome = "allowed" if verdict.allowed else "blocked"
        GUARDRAIL_VERDICTS_TOTAL.labels(verdict.guardrail, stage, outcome).inc()
        log = logger.info if verdict.allowed else logger.warning
        log(
            "guardrail_verdict",
            guardrail=verdict.guardrail,
            stage=stage,
            outcome=outcome,
            reasons=verdict.reasons,
        )
        if not verdict.allowed:
            raise GuardrailBlocked(stage, verdict)

    def complete(self, system: str, user: str) -> str | None:
        self._check(user, "prompt")
        text = self._llm.complete(system, user)
        if text:
            self._check(text, "response")
        return text

    def parse(self, system: str, user: str, schema: type[T]) -> T | None:
        self._check(user, "prompt")
        result = self._llm.parse(system, user, schema)
        if result is not None:
            self._check(result.model_dump_json(), "response")
        return result
