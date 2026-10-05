"""Runs the golden set against the deployed desk assistant (MM-132).

    python -m evaluation.desk_eval --agent projects/.../reasoningEngines/<id>

1. Each golden case is one fresh chat session as its user, through the same
   Agent Runtime REST client the API uses.
2. Deterministic checks (evaluation.checks): tool choice, refusals, scope,
   and grounding of every amount. All must pass.
3. Vertex AI Gen AI evaluation rubrics (hallucination, final response
   quality) over the same turns; each mean score must reach its threshold.
   Skip with --no-rubrics.

Writes a JSON report and, in GitHub Actions, a summary table. Exits 1 on any
failure, so the CI job goes red on a regression.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import structlog

from api.desk import AgentRuntimeDesk, _google_session
from evaluation.checks import CheckResult, TurnRecord, check, summarize, turn_record
from evaluation.golden import GOLDEN_CASES, TOOL_DESCRIPTIONS, GoldenCase

logger = structlog.get_logger()

# Minimum mean score per Vertex rubric metric (scores are 0..1).
RUBRIC_THRESHOLDS = {
    "hallucination": 0.75,
    "final_response_quality": 0.7,
}


def run_cases(desk: Any, cases: list[GoldenCase]) -> list[tuple[TurnRecord, CheckResult]]:
    results = []
    for case in cases:
        try:
            _, events = desk.run_turn(case.user, case.prompt, None)
            turn = turn_record(case.case_id, events)
        except Exception as exc:  # noqa: BLE001 -- one failed case shouldn't hide the rest
            turn = TurnRecord(case_id=case.case_id, answer="", tools=[], tool_outputs=[], events=[])
            logger.error("desk_eval_case_error", case_id=case.case_id, error=str(exc)[:200])
        result = check(case, turn)
        logger.info(
            "desk_eval_case",
            case_id=case.case_id,
            passed=result.passed,
            tools=turn.tools,
            failures=result.failures,
        )
        results.append((turn, result))
    return results


def rubric_scores(
    client: Any, cases: list[GoldenCase], turns: list[TurnRecord]
) -> dict[str, float | None]:
    """Mean score per rubric metric from Vertex AI Gen AI evaluation."""
    from google.genai import types as genai_types
    from vertexai._genai import types

    agent_info = agent_info_for_rubrics()

    eval_cases = [
        types.EvalCase(
            eval_case_id=case.case_id,
            prompt=genai_types.Content(role="user", parts=[genai_types.Part(text=case.prompt)]),
            responses=[
                types.ResponseCandidate(
                    response=genai_types.Content(
                        role="model", parts=[genai_types.Part(text=turn.answer or "(no answer)")]
                    )
                )
            ],
            intermediate_events=[
                types.Event(
                    content=genai_types.Content.model_validate(event["content"]),
                    author=event.get("author"),
                )
                for event in turn.events
                if event.get("content") and not event.get("partial")
            ],
            agent_info=agent_info,
        )
        for case, turn in zip(cases, turns, strict=True)
    ]
    # Tool choice is scored by the deterministic trajectory checks instead:
    # the managed tool_use_quality rubric rejected our agent traces
    # ("tool_usage is required") even with tool calls present (2026-10-05).
    metrics = [types.RubricMetric.HALLUCINATION, types.RubricMetric.FINAL_RESPONSE_QUALITY]
    result = client.evals.evaluate(
        dataset=types.EvaluationDataset(eval_cases=eval_cases), metrics=metrics
    )
    scores: dict[str, float | None] = {}
    for summary in result.summary_metrics or []:
        name = re.sub(r"_v\d+$", "", (summary.metric_name or "").split("/")[-1].lower())
        scores[name] = summary.mean_score
    return scores


def agent_info_for_rubrics() -> Any:
    """The agent and its tool declarations, which the tool-use rubric needs."""
    from google.genai import types as genai_types
    from vertexai._genai.types import evals

    from desk_assistant.agent import INSTRUCTION

    tools = [
        genai_types.Tool(
            function_declarations=[
                genai_types.FunctionDeclaration(name=name, description=description)
                for name, description in TOOL_DESCRIPTIONS.items()
            ]
        )
    ]
    config = evals.AgentConfig(
        agent_id="margin_desk", instruction=INSTRUCTION, tools=tools, description="Margin desk"
    )
    return evals.AgentInfo(
        name="margin_desk", agents={"margin_desk": config}, root_agent_id="margin_desk"
    )


def failed_rubrics(scores: dict[str, float | None]) -> list[str]:
    failures = []
    for metric, threshold in RUBRIC_THRESHOLDS.items():
        score = scores.get(metric)
        if score is None or score < threshold:
            failures.append(f"{metric}: {score} < {threshold}")
    return failures


def report(
    results: list[tuple[TurnRecord, CheckResult]],
    scores: dict[str, float | None] | None,
) -> dict[str, Any]:
    checks = [result for _, result in results]
    return {
        "deterministic": summarize(checks),
        "cases": [
            {
                "case_id": turn.case_id,
                "passed": result.passed,
                "failures": result.failures,
                "tools": turn.tools,
                "answer": turn.answer,
            }
            for turn, result in results
        ],
        "rubrics": scores,
        "rubric_failures": failed_rubrics(scores) if scores is not None else [],
    }


def markdown(data: dict[str, Any]) -> str:
    det = data["deterministic"]
    lines = [
        "## Desk assistant evaluation (MM-132)",
        f"**Deterministic checks:** {det['passed']}/{det['total']} passed",
        "",
        "| Case | Result | Tools | Failures |",
        "|---|---|---|---|",
    ]
    for case in data["cases"]:
        result = "pass" if case["passed"] else "**FAIL**"
        tools = ", ".join(case["tools"]) or "—"
        lines.append(f"| {case['case_id']} | {result} | {tools} | {'; '.join(case['failures'])} |")
    if data["rubrics"] is not None:
        lines += ["", "| Rubric (Vertex AI) | Mean | Threshold |", "|---|---|---|"]
        for metric, threshold in RUBRIC_THRESHOLDS.items():
            score = data["rubrics"].get(metric)
            shown = f"{score:.2f}" if isinstance(score, float) else "n/a"
            lines.append(f"| {metric} | {shown} | {threshold} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", required=True, help="projects/.../reasoningEngines/<id>")
    parser.add_argument("--out", default="desk-eval-report.json")
    parser.add_argument("--no-rubrics", action="store_true", help="deterministic checks only")
    args = parser.parse_args(argv)

    location = args.agent.split("/locations/", 1)[1].split("/", 1)[0]
    project = args.agent.split("projects/", 1)[1].split("/", 1)[0]
    desk = AgentRuntimeDesk(args.agent, location, _google_session())
    results = run_cases(desk, GOLDEN_CASES)

    scores = None
    if not args.no_rubrics:
        import vertexai

        client = vertexai.Client(project=project, location=location)
        scores = rubric_scores(client, GOLDEN_CASES, [turn for turn, _ in results])

    data = report(results, scores)
    Path(args.out).write_text(json.dumps(data, indent=2), encoding="utf-8")
    summary = markdown(data)
    print(summary)
    if step_summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(step_summary, "a", encoding="utf-8") as handle:
            handle.write(summary)

    ok = data["deterministic"]["passed"] == data["deterministic"]["total"]
    return 0 if ok and not data["rubric_failures"] else 1


if __name__ == "__main__":
    sys.exit(main())
