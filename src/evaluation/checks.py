"""Deterministic checks for one desk-assistant turn (MM-132).

The grounding check is golden rule 1 made testable: every amount the agent
states must be a number some tool returned in the same turn (to the cent),
so a figure the model computed or made up fails the case.
"""

import json
import re
from typing import Any

from pydantic import BaseModel

from evaluation.golden import GoldenCase

# Numbers worth grounding: decimals, comma-grouped, or 3+ digits. Years,
# dates, counterparty ids (CP-3) and list numbering are excluded below.
_NUMBER = re.compile(r"(?<![\w.-])\d[\d,]*(?:\.\d+)?(?![\w-])")
_DATE_LIKE = re.compile(r"\d{4}-\d{2}-\d{2}|\d{1,2}:\d{2}")
_TOLERANCE = 0.01  # one cent


class TurnRecord(BaseModel):
    case_id: str
    answer: str
    tools: list[str]
    tool_outputs: list[str]
    events: list[dict]


class CheckResult(BaseModel):
    case_id: str
    passed: bool
    failures: list[str]


def turn_record(case_id: str, events: list[dict]) -> TurnRecord:
    """Splits a turn's raw Agent Runtime events into answer, tools called
    and tool outputs."""
    answer, tools, outputs = "", [], []
    for event in events:
        if event.get("partial"):
            continue
        content = event.get("content") or {}
        for part in content.get("parts") or []:
            if call := part.get("function_call"):
                tools.append(call.get("name", ""))
            if result := part.get("function_response"):
                outputs.append(json.dumps(result.get("response", result), default=str))
            if part.get("text") and content.get("role") == "model":
                answer = part["text"]
    return TurnRecord(
        case_id=case_id, answer=answer.strip(), tools=tools, tool_outputs=outputs, events=events
    )


def amounts(text: str) -> list[float]:
    cleaned = _DATE_LIKE.sub(" ", text)
    values = []
    for match in _NUMBER.finditer(cleaned):
        raw = match.group(0).rstrip(".,")
        digits = raw.replace(",", "")
        if "." not in digits and "," not in raw and len(digits) < 3:
            continue  # small integers: counts, list numbering
        value = float(digits)
        if "." not in digits and "," not in raw and 1900 <= value <= 2100:
            continue  # a year
        values.append(value)
    return values


def ungrounded_amounts(answer: str, tool_outputs: list[str]) -> list[float]:
    available = [value for output in tool_outputs for value in _all_numbers(output)]
    return [
        value
        for value in amounts(answer)
        if not any(abs(value - known) <= _TOLERANCE for known in available)
    ]


def _all_numbers(text: str) -> list[float]:
    return [float(m.replace(",", "")) for m in re.findall(r"-?\d[\d,]*(?:\.\d+)?", text)]


def check(case: GoldenCase, turn: TurnRecord) -> CheckResult:
    failures: list[str] = []
    if not turn.answer:
        failures.append("no answer")
    if case.expect_any_tool and not set(case.expect_any_tool) & set(turn.tools):
        failures.append(f"expected one of {case.expect_any_tool}, called {turn.tools or 'none'}")
    if "*" in case.forbid_tools and turn.tools:
        failures.append(f"expected no tool call, called {turn.tools}")
    forbidden = set(case.forbid_tools) - {"*"}
    if called := sorted(forbidden & set(turn.tools)):
        failures.append(f"called forbidden tools {called}")
    lowered = turn.answer.lower()
    missing = [term for term in case.must_mention if term.lower() not in lowered]
    if missing:
        failures.append(f"answer doesn't mention {missing}")
    leaked = [term for term in case.must_not_mention if _mentions(turn.answer, term)]
    if leaked:
        failures.append(f"answer mentions {leaked}")
    if case.no_amounts and amounts(turn.answer):
        failures.append(f"expected no amounts, found {amounts(turn.answer)}")
    if case.grounded and (ungrounded := ungrounded_amounts(turn.answer, turn.tool_outputs)):
        failures.append(f"amounts not from any tool: {ungrounded}")
    return CheckResult(case_id=case.case_id, passed=not failures, failures=failures)


def _mentions(text: str, term: str) -> bool:
    """Whole-token match, so 'CP-1' doesn't match inside 'CP-10'."""
    return re.search(rf"(?<![\w-]){re.escape(term)}(?![\w])", text, re.IGNORECASE) is not None


def summarize(results: list[CheckResult]) -> dict[str, Any]:
    passed = sum(result.passed for result in results)
    return {"passed": passed, "total": len(results), "pass_rate": passed / len(results)}
