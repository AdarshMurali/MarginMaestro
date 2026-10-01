"""In-code baseline guardrail (MM-113): always available, no network, and the
post-trial fallback for Model Armor (ADR-0017). Deliberately conservative --
it only blocks clear prompt-injection phrasing aimed at the model, so ordinary
CSA, policy and dispute text never trips it. Model Armor (MM-114) is the
broader screen.
"""

import re

from ports.guardrail import Stage, Verdict

# Instructions addressed *to the model*, the classic injection shapes. Matched
# case-insensitively anywhere in the text (including retrieved RAG chunks and
# client replies, which are untrusted).
INJECTION_PATTERNS: dict[str, re.Pattern[str]] = {
    name: re.compile(pattern, re.IGNORECASE)
    for name, pattern in {
        "ignore_instructions": r"\b(ignore|disregard|forget)\b.{0,30}\b(previous|prior|above|earlier|all|your)\b.{0,20}\b(instructions?|rules|prompts?|guidance|guidelines|directions?)\b",
        # Asking the model to assert facts the source doesn't contain.
        "fabricate_source": r"\bpretend (that )?the (csa|document|agreement|contract|policy)\b",
        # Not "act as ...": "act as calculation agent" is standard ISDA wording.
        "role_override": r"\byou are now\b",
        "reveal_system_prompt": r"\b(reveal|print|show|repeat)\b.{0,30}\b(system prompt|your instructions|hidden instructions)\b",
        "developer_mode": r"\b(developer|god|jailbreak|DAN) mode\b",
    }.items()
}


class InCodeGuardrail:
    name = "incode"

    def screen(self, text: str, stage: Stage) -> Verdict:
        if stage == "response":
            # Output checks that matter here (exact amounts, citations) live in
            # the agents themselves (MM-116); nothing generic to screen.
            return Verdict(allowed=True, guardrail=self.name)
        reasons = [name for name, pattern in INJECTION_PATTERNS.items() if pattern.search(text)]
        return Verdict(allowed=not reasons, guardrail=self.name, reasons=reasons)


class NoGuardrail:
    """GUARDRAIL_PROVIDER=none: explicit opt-out, for local experiments only."""

    name = "none"

    def screen(self, text: str, stage: Stage) -> Verdict:
        return Verdict(allowed=True, guardrail=self.name)
