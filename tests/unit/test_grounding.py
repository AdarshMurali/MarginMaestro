"""MM-116: answers must be grounded in the right documents."""

from unittest.mock import MagicMock, patch

import pytest

from agents.csa_rag import CSATermsUnavailableError, answer_csa_terms
from agents.reconciliation import MANUAL_REVIEW, draft_resolution
from calc.trade_diff import BreakItem, BreakType
from config.settings import Settings
from rag.retriever import RetrievedChunk


def _chunk(counterparty_id: str, section: str = "Threshold") -> RetrievedChunk:
    return RetrievedChunk(
        text=f"{counterparty_id} terms",
        source_file=f"csa/{counterparty_id}.md",
        doc_type="csa",
        counterparty_id=counterparty_id,
        effective_date="2026-08-16",
        section=section,
        distance=0.1,
    )


def test_csa_terms_only_cite_the_counterpartys_own_csa():
    extraction = MagicMock(
        threshold=1.0,
        mta=2.0,
        currency="USD",
        eligible_collateral=[],
        haircuts=[],
        rating_triggers=[],
    )
    llm = MagicMock()
    llm.parse.return_value = extraction
    with patch(
        "agents.csa_rag.retrieve", return_value=[_chunk("CP-3"), _chunk("CP-9"), _chunk("")]
    ):
        result = answer_csa_terms("CP-3", settings=Settings(_env_file=None), llm=llm)

    assert {c.source_file for c in result.citations} == {"csa/CP-3.md"}
    sent = llm.parse.call_args.args[1]
    assert "CP-9 terms" not in sent


def test_csa_terms_unavailable_when_only_other_documents_come_back():
    llm = MagicMock()
    with (
        patch("agents.csa_rag.retrieve", return_value=[_chunk("CP-9")]),
        pytest.raises(CSATermsUnavailableError),
    ):
        answer_csa_terms("CP-3", settings=Settings(_env_file=None), llm=llm)
    llm.parse.assert_not_called()


def test_no_retrieved_precedent_means_manual_review_without_asking_the_model():
    llm = MagicMock()
    breaks = [
        BreakItem(
            ticker="AAPL",
            break_type=next(iter(BreakType)),
            our_quantity=10.0,
            counterparty_quantity=8.0,
        )
    ]
    with patch("agents.reconciliation.retrieve", return_value=[]):
        resolution, citations = draft_resolution(breaks, settings=Settings(_env_file=None), llm=llm)

    assert resolution == MANUAL_REVIEW
    assert citations == []
    llm.complete.assert_not_called()


# --- collateral label canonicalisation (MM-117) -------------------------------------

DOC = (
    "## Eligible Collateral\n\n"
    "- Cash (USD) (haircut: 0%)\n"
    "- Investment-grade corporate bonds (haircut: 8%)\n"
    "- US Treasury securities (haircut: 2%)\n"
)


@pytest.mark.parametrize(
    ("extracted", "expected"),
    [
        ("Cash (USD)", "Cash (USD)"),  # exact
        ("Cash", "Cash (USD)"),  # model dropped the qualifier
        ("cash", "Cash (USD)"),  # case
        ("Treasury securities", "US Treasury securities"),  # contained
        ("Gold", "Gold"),  # not in the document: kept, never invented
    ],
)
def test_collateral_names_map_back_to_the_documents_own_labels(extracted, expected):
    from agents.csa_rag import canonical_collateral_name

    assert canonical_collateral_name(extracted, DOC) == expected


def test_ambiguous_names_are_left_alone():
    from agents.csa_rag import canonical_collateral_name

    doc = "- Cash (USD) (haircut: 0%)\n- Cash (EUR) (haircut: 1%)\n"
    assert canonical_collateral_name("Cash", doc) == "Cash"
