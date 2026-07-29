from unittest.mock import MagicMock, patch

import pytest

from agents.csa_rag import (
    CSATermsUnavailableError,
    _CSATermsExtraction,
    _HaircutEntry,
    answer_csa_terms,
)
from rag.models import Citation
from rag.retriever import RetrievedChunk

SAMPLE_CHUNKS = [
    RetrievedChunk(
        text="## Threshold\n\nThe Threshold applicable to Yang Partners is USD 90,000.",
        source_file="csa/CP-3.md",
        doc_type="csa",
        counterparty_id="CP-3",
        effective_date="2026-07-26",
        section="Threshold",
        distance=0.1,
    ),
    RetrievedChunk(
        text="## Minimum Transfer Amount\n\nThe MTA applicable to Yang Partners is USD 19,000.",
        source_file="csa/CP-3.md",
        doc_type="csa",
        counterparty_id="CP-3",
        effective_date="2026-07-26",
        section="Minimum Transfer Amount",
        distance=0.15,
    ),
]

SAMPLE_EXTRACTION = _CSATermsExtraction(
    threshold=90000.0,
    mta=19000.0,
    currency="USD",
    eligible_collateral=["Investment-grade corporate bonds", "US Treasury securities"],
    haircuts=[
        _HaircutEntry(collateral_type="Investment-grade corporate bonds", haircut=0.08),
        _HaircutEntry(collateral_type="US Treasury securities", haircut=0.02),
    ],
    rating_triggers=["A downgrade of Yang Partners below BB triggers a review."],
)


def _mock_openai_client(extraction: _CSATermsExtraction | None) -> MagicMock:
    client = MagicMock()
    client.chat.completions.parse.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(parsed=extraction))]
    )
    return client


class TestAnswerCsaTerms:
    def test_retrieves_scoped_to_counterparty_and_csa_doc_type(self) -> None:
        with patch("agents.csa_rag.retrieve", return_value=SAMPLE_CHUNKS) as mock_retrieve:
            answer_csa_terms("CP-3", openai_client=_mock_openai_client(SAMPLE_EXTRACTION))

        _, kwargs = mock_retrieve.call_args
        assert kwargs["counterparty_id"] == "CP-3"
        assert kwargs["doc_type"] == "csa"

    def test_custom_question_is_passed_through(self) -> None:
        with patch("agents.csa_rag.retrieve", return_value=SAMPLE_CHUNKS) as mock_retrieve:
            answer_csa_terms(
                "CP-3",
                question="custom question?",
                openai_client=_mock_openai_client(SAMPLE_EXTRACTION),
            )

        args, _ = mock_retrieve.call_args
        assert args[0] == "custom question?"

    def test_builds_result_from_llm_extraction_and_chunk_citations(self) -> None:
        with patch("agents.csa_rag.retrieve", return_value=SAMPLE_CHUNKS):
            result = answer_csa_terms("CP-3", openai_client=_mock_openai_client(SAMPLE_EXTRACTION))

        assert result.counterparty_id == "CP-3"
        assert result.threshold == 90000.0
        assert result.mta == 19000.0
        assert result.eligible_collateral == SAMPLE_EXTRACTION.eligible_collateral
        assert result.haircuts == {
            "Investment-grade corporate bonds": 0.08,
            "US Treasury securities": 0.02,
        }
        assert result.citations == [
            Citation(source_file="csa/CP-3.md", section="Threshold"),
            Citation(source_file="csa/CP-3.md", section="Minimum Transfer Amount"),
        ]

    def test_no_retrieved_chunks_raises(self) -> None:
        with (
            patch("agents.csa_rag.retrieve", return_value=[]),
            pytest.raises(CSATermsUnavailableError, match="CP-99"),
        ):
            answer_csa_terms("CP-99", openai_client=_mock_openai_client(SAMPLE_EXTRACTION))

    def test_llm_failing_to_parse_raises(self) -> None:
        with (
            patch("agents.csa_rag.retrieve", return_value=SAMPLE_CHUNKS),
            pytest.raises(CSATermsUnavailableError, match="CP-3"),
        ):
            answer_csa_terms("CP-3", openai_client=_mock_openai_client(None))
