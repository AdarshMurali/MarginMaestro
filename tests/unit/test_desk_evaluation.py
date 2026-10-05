"""MM-132: the desk assistant's evaluation -- golden set, deterministic checks
(trajectory, refusals, scope, grounding) and the runner. No live calls."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from evaluation import checks, desk_eval
from evaluation.golden import GOLDEN_CASES, TOOL_DESCRIPTIONS, GoldenCase


def _events(answer: str, calls: list[tuple[str, dict]] | None = None) -> list[dict]:
    events = []
    for name, response in calls or []:
        events.append({"content": {"role": "model", "parts": [{"function_call": {"name": name}}]}})
        events.append(
            {
                "content": {
                    "role": "user",
                    "parts": [{"function_response": {"name": name, "response": response}}],
                }
            }
        )
    events.append({"partial": True, "content": {"role": "model", "parts": [{"text": "draft"}]}})
    events.append(
        {"author": "margin_desk", "content": {"role": "model", "parts": [{"text": answer}]}}
    )
    return events


CALLS = [("list_margin_calls", {"result": [{"counterparty_id": "CP-3", "call_amount": 161716.66}]})]


# --- turn parsing -----------------------------------------------------------------


def test_turn_record_splits_answer_tools_and_outputs():
    turn = checks.turn_record("c", _events("CP-3: 161716.66 USD", CALLS))

    assert turn.answer == "CP-3: 161716.66 USD"
    assert turn.tools == ["list_margin_calls"]
    assert "161716.66" in turn.tool_outputs[0]


# --- grounding --------------------------------------------------------------------


@pytest.mark.parametrize(
    "answer, expected",
    [
        ("CP-3 owes 161,716.66 USD", []),
        ("CP-3 owes 161716.66 USD", []),
        ("CP-3 owes 161716.659 USD", []),  # within a cent
        ("CP-3 owes 194060.00 USD", [194060.0]),  # computed, not from a tool
        ("Call raised on 2026-10-02 at 17:30 for CP-3, 2 calls in 2026", []),
    ],
)
def test_grounding_flags_only_figures_no_tool_returned(answer, expected):
    outputs = [json.dumps({"call_amount": 161716.66})]

    assert checks.ungrounded_amounts(answer, outputs) == expected


def test_amounts_skip_small_counts_years_and_ids():
    assert checks.amounts("CP-3 has 2 calls since 2025, see item 12") == []
    assert checks.amounts("USD 90,000 and 69.33") == [90000.0, 69.33]


# --- per-case checks --------------------------------------------------------------


def _check(case: GoldenCase, answer: str, calls=None):
    return checks.check(case, checks.turn_record(case.case_id, _events(answer, calls)))


def test_expected_tool_must_be_called():
    case = GoldenCase(case_id="c", user="u", prompt="p", expect_any_tool=["list_margin_calls"])

    assert _check(case, "CP-3: 161716.66", CALLS).passed
    result = _check(case, "No idea.")
    assert not result.passed and "expected one of" in result.failures[0]


def test_action_requests_must_call_no_tool():
    case = GoldenCase(
        case_id="c", user="u", prompt="p", forbid_tools=["*"], must_mention=["dashboard"]
    )

    assert _check(case, "Use the dashboard to approve.").passed
    assert not _check(case, "Done via dashboard.", CALLS).passed


def test_named_forbidden_tool():
    case = GoldenCase(case_id="c", user="u", prompt="p", forbid_tools=["list_margin_calls"])

    assert "called forbidden tools" in _check(case, "x 161716.66", CALLS).failures[0]


def test_scope_leaks_use_whole_token_matching():
    case = GoldenCase(case_id="c", user="u", prompt="p", must_not_mention=["CP-1"])

    assert _check(case, "Only CP-10 and CP-3 here.").passed
    assert not _check(case, "CP-1 has a call.").passed


def test_refused_lookup_has_no_amounts():
    case = GoldenCase(case_id="c", user="u", prompt="p", no_amounts=True)

    assert _check(case, "That counterparty isn't available to you.").passed
    assert not _check(case, "Its threshold is USD 220,000.").passed


def test_ungrounded_figure_fails_the_case():
    case = GoldenCase(case_id="c", user="u", prompt="p")

    result = _check(case, "A 20% fall would make it 194060.00 USD.", CALLS)

    assert not result.passed
    assert "amounts not from any tool" in result.failures[0]


def test_empty_answer_fails():
    case = GoldenCase(case_id="c", user="u", prompt="p", grounded=False)

    assert _check(case, "").failures == ["no answer"]


def test_summary():
    results = [checks.CheckResult(case_id=str(i), passed=i < 3, failures=[]) for i in range(4)]

    assert checks.summarize(results) == {"passed": 3, "total": 4, "pass_rate": 0.75}


# --- golden set -------------------------------------------------------------------


def test_golden_cases_are_unique_and_use_known_tools():
    ids = [case.case_id for case in GOLDEN_CASES]
    assert len(ids) == len(set(ids)) >= 10
    for case in GOLDEN_CASES:
        assert set(case.expect_any_tool) <= set(TOOL_DESCRIPTIONS)
        assert set(case.forbid_tools) - {"*"} <= set(TOOL_DESCRIPTIONS)


def test_tool_descriptions_match_the_real_mcp_servers():
    from mcp_servers.http import SERVERS

    names = set()
    for loader in SERVERS.values():
        names |= {tool.name for tool in asyncio.run(loader().list_tools())}

    assert set(TOOL_DESCRIPTIONS) == names


def test_golden_set_covers_refusals_scope_and_grounding():
    assert any("*" in case.forbid_tools for case in GOLDEN_CASES)
    assert any(case.must_not_mention for case in GOLDEN_CASES)
    assert any(case.no_amounts for case in GOLDEN_CASES)
    assert all(case.grounded for case in GOLDEN_CASES)


# --- runner -----------------------------------------------------------------------


class FakeDesk:
    def __init__(self, fail_on: str | None = None) -> None:
        self.fail_on = fail_on
        self.calls: list[tuple[str, str]] = []

    def run_turn(self, user: str, prompt: str, session_id):
        self.calls.append((user, prompt))
        if prompt == self.fail_on:
            raise RuntimeError("agent down")
        return "s", _events("CP-3: 161716.66 USD", CALLS)


def test_each_case_runs_as_its_own_user_in_a_fresh_session():
    cases = GOLDEN_CASES[:2]
    desk = FakeDesk()

    results = desk_eval.run_cases(desk, cases)

    assert desk.calls == [(c.user, c.prompt) for c in cases]
    assert len(results) == 2


def test_a_failing_case_is_recorded_not_raised():
    case = GoldenCase(case_id="c", user="u", prompt="boom", expect_any_tool=["list_margin_calls"])

    [(turn, result)] = desk_eval.run_cases(FakeDesk(fail_on="boom"), [case])

    assert turn.answer == "" and not result.passed


def test_rubric_thresholds():
    assert desk_eval.failed_rubrics({"hallucination": 0.9, "final_response_quality": 0.8}) == []
    failures = desk_eval.failed_rubrics({"hallucination": 0.5})
    assert len(failures) == 2  # one low, one missing


def test_rubric_scores_parse_versioned_metric_names():
    summary = [
        SimpleNamespace(metric_name="hallucination_v2", mean_score=0.9),
        SimpleNamespace(metric_name="final_response_quality_v1", mean_score=0.8),
    ]
    client = SimpleNamespace(
        evals=SimpleNamespace(evaluate=lambda **kw: SimpleNamespace(summary_metrics=summary))
    )
    turn = checks.turn_record("c", _events("CP-3: 161716.66 USD", CALLS))

    scores = desk_eval.rubric_scores(client, GOLDEN_CASES[:1], [turn])

    assert scores == {"hallucination": 0.9, "final_response_quality": 0.8}


def test_report_and_markdown():
    turn = checks.turn_record("c", _events("ok"))
    data = desk_eval.report(
        [(turn, checks.CheckResult(case_id="c", passed=False, failures=["no answer"]))],
        {"hallucination": 0.9, "final_response_quality": 0.8},
    )

    text = desk_eval.markdown(data)

    assert data["deterministic"]["passed"] == 0
    assert "| c | **FAIL** |" in text
    assert "| hallucination | 0.90 | 0.75 |" in text


def test_main_writes_report_and_summary_to_fixed_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(desk_eval, "_google_session", lambda: object())
    monkeypatch.setattr(desk_eval, "AgentRuntimeDesk", lambda *a: FakeDesk())
    monkeypatch.setattr(desk_eval, "GOLDEN_CASES", GOLDEN_CASES[:1])
    agent = "projects/p/locations/us-central1/reasoningEngines/1"

    code = desk_eval.main(["--agent", agent, "--no-rubrics"])

    assert code == 0
    report = json.loads((tmp_path / desk_eval.REPORT_FILE).read_text())
    assert report["deterministic"]["total"] == 1
    assert "Desk assistant evaluation" in (tmp_path / desk_eval.SUMMARY_FILE).read_text()


def test_output_paths_are_not_configurable():
    with pytest.raises(SystemExit):
        desk_eval.main(["--agent", "projects/p/locations/l/reasoningEngines/1", "--out", "/etc/x"])


def test_agent_info_declares_every_tool():
    info = desk_eval.agent_info_for_rubrics()

    declared = {f.name for f in info.agents["margin_desk"].tools[0].function_declarations}
    assert declared == set(TOOL_DESCRIPTIONS)
