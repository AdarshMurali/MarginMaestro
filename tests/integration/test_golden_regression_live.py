"""MM-112: golden regression -- the CSA terms the margin math depends on must
come out the same whichever LLM extracts them.

For every counterparty's CSA document, Gemini (Vertex AI) and OpenAI each run
the CSA agent's real extraction (same system prompt and schema). Both are
compared with the ground truth parsed straight from the document, so a
disagreement says which model is wrong, not just that they differ.

The document is given to the model directly (no retrieval) so this isolates
the model; retrieval is covered by the pgvector tests.

Live: real API calls (fractions of a cent each). Needs GCP_PROJECT_ID + ADC
for Vertex AI and OPENAI_API_KEY:
    pytest -m live tests/integration/test_golden_regression_live.py -s
"""

import re
import time
from pathlib import Path

import pytest

from adapters.factory import get_llm
from agents.csa_rag import SYSTEM_PROMPT, _CSATermsExtraction, canonical_collateral_name
from config.settings import Settings

pytestmark = pytest.mark.live

CSA_DIR = Path(__file__).resolve().parents[2] / "data" / "documents" / "csa"
COUNTERPARTIES = sorted(p.stem for p in CSA_DIR.glob("CP-*.md"))
LATENCIES: dict[str, list[float]] = {"vertex": [], "openai": []}


def _ground_truth(text: str) -> dict:
    """The documents are templated, so these patterns are exact."""
    money = lambda pattern: float(re.search(pattern, text).group(1).replace(",", ""))
    haircuts = {
        name.strip(): int(pct) / 100
        for name, pct in re.findall(r"^- (.+?) \(haircut: (\d+)%\)", text, re.MULTILINE)
    }
    triggers = [
        (grade, float(amount.replace(",", "")))
        for grade, amount in re.findall(
            r"falls below (\w+), the Threshold is reduced to USD ([\d,]+)", text
        )
    ]
    return {
        "threshold": money(r"Threshold applicable to .+? is USD ([\d,]+)"),
        "mta": money(r"\(MTA\) applicable to .+? is USD ([\d,]+)"),
        "currency": "USD",
        "haircuts": haircuts,
        "triggers": sorted(triggers),
    }


def _normalise(extraction: _CSATermsExtraction, document: str) -> dict:
    return {
        "threshold": extraction.threshold,
        "mta": extraction.mta,
        "currency": extraction.currency,
        # Same canonicalisation the CSA agent applies (MM-117).
        "haircuts": {
            canonical_collateral_name(h.collateral_type.strip(), document): round(h.haircut, 4)
            for h in extraction.haircuts
        },
        "triggers": sorted(
            (str(getattr(t.below_grade, "value", t.below_grade)), float(t.reduced_threshold))
            for t in extraction.rating_triggers
        ),
    }


@pytest.fixture(scope="module", params=["vertex", "openai"])
def provider(request):
    settings = Settings(llm_provider=request.param)
    if request.param == "vertex" and not settings.gcp_project_id:
        pytest.skip("GCP_PROJECT_ID not set")
    if request.param == "openai" and not settings.openai_api_key:
        pytest.skip("OPENAI_API_KEY not set")
    return request.param, get_llm(settings)


@pytest.mark.parametrize("counterparty", COUNTERPARTIES)
def test_extraction_matches_the_document(provider, counterparty):
    name, llm = provider
    document = (CSA_DIR / f"{counterparty}.md").read_text(encoding="utf-8")
    question = (
        f"What are {counterparty}'s CSA terms -- threshold, minimum transfer amount, "
        "eligible collateral, haircuts, and rating triggers?"
    )

    started = time.monotonic()
    extraction = llm.parse(SYSTEM_PROMPT, f"{question}\n\n---\n\n{document}", _CSATermsExtraction)
    LATENCIES[name].append(time.monotonic() - started)

    assert extraction is not None, f"{name} returned no extraction for {counterparty}"
    assert _normalise(extraction, document) == _ground_truth(document)


def test_latency_report():
    """Not an assertion on speed -- prints the distribution for the progress log."""
    for name, samples in LATENCIES.items():
        if samples:
            ordered = sorted(samples)
            print(
                f"\n{name}: n={len(ordered)} median={ordered[len(ordered) // 2]:.1f}s "
                f"max={ordered[-1]:.1f}s"
            )
