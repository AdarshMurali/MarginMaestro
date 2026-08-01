from datetime import date
from unittest.mock import MagicMock, patch

from agents.reconciliation import draft_resolution, reconcile_call
from calc.trade_diff import BreakItem, BreakType
from persistence.models import AssetClass, Position
from rag.retriever import RetrievedChunk

SAMPLE_CHUNKS = [
    RetrievedChunk(
        text="A stale-price break does not require escalation once the correct price is confirmed.",
        source_file="exceptions/exception_rules.md",
        doc_type="exceptions",
        counterparty_id="",
        effective_date="2026-08-01",
        section="Stale Price Exception",
        distance=0.1,
    ),
    RetrievedChunk(
        text="Applied the Stale Price Exception; the current-day close was treated as authoritative.",
        source_file="disputes/dispute-001-stale-price.md",
        doc_type="disputes",
        counterparty_id="",
        effective_date="2026-08-01",
        section="Resolution",
        distance=0.15,
    ),
]

BREAK_ITEMS = [
    BreakItem(
        ticker="AAPL",
        break_type=BreakType.QUANTITY_MISMATCH,
        our_quantity=100.0,
        counterparty_quantity=80.0,
    )
]


def _position(id_: str, ticker: str, quantity: float) -> Position:
    return Position(
        id=id_,
        portfolio_id="PF-1",
        ticker=ticker,
        asset_class=AssetClass.EQUITY,
        quantity=quantity,
        trade_date=date(2026, 1, 1),
    )


def _mock_openai_client(text: str | None) -> MagicMock:
    client = MagicMock()
    client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=text))]
    )
    return client


class TestDraftResolution:
    def test_queries_both_exceptions_and_disputes_doc_types(self) -> None:
        with patch("agents.reconciliation.retrieve", return_value=SAMPLE_CHUNKS) as mock_retrieve:
            draft_resolution(BREAK_ITEMS, openai_client=_mock_openai_client("resolution text"))

        doc_types = {call.kwargs["doc_type"] for call in mock_retrieve.call_args_list}
        assert doc_types == {"exceptions", "disputes"}

    def test_returns_citations_from_retrieved_chunks(self) -> None:
        with patch("agents.reconciliation.retrieve", return_value=SAMPLE_CHUNKS):
            _, citations = draft_resolution(
                BREAK_ITEMS, openai_client=_mock_openai_client("resolution text")
            )

        assert len(citations) == 4  # 2 chunks x 2 doc_type queries (exceptions + disputes)
        assert citations[0].source_file == "exceptions/exception_rules.md"

    def test_empty_llm_response_falls_back_to_manual_review_text(self) -> None:
        with patch("agents.reconciliation.retrieve", return_value=SAMPLE_CHUNKS):
            resolution, _ = draft_resolution(BREAK_ITEMS, openai_client=_mock_openai_client(None))

        assert "manual" in resolution.lower()


class TestReconcileCall:
    def test_agreed_within_tolerance_never_calls_the_llm(self) -> None:
        our = [_position("POS-1", "AAPL", 100.0)]
        counterparty = [_position("POS-1", "AAPL", 100.0)]
        client = _mock_openai_client("should not be used")

        result = reconcile_call(
            our,
            counterparty,
            our_total=1000.0,
            counterparty_total=1010.0,
            tolerance=100.0,
            openai_client=client,
        )

        assert result.agreed is True
        assert result.break_items == []
        assert result.suggested_resolution is None
        assert result.citations == []
        client.chat.completions.create.assert_not_called()

    def test_disagreed_beyond_tolerance_drafts_a_resolution(self) -> None:
        our = [_position("POS-1", "AAPL", 100.0)]
        counterparty = [_position("POS-1", "AAPL", 80.0)]

        with patch("agents.reconciliation.retrieve", return_value=SAMPLE_CHUNKS):
            result = reconcile_call(
                our,
                counterparty,
                our_total=1_000_000.0,
                counterparty_total=900_000.0,
                tolerance=100.0,
                openai_client=_mock_openai_client("Apply the Stale Price Exception."),
            )

        assert result.agreed is False
        assert len(result.break_items) == 1
        assert result.suggested_resolution == "Apply the Stale Price Exception."
        assert len(result.citations) == 4
