from rag.chunker import chunk_markdown, extract_effective_date

SAMPLE_DOC = """# Credit Support Annex — Rodriguez Partners (CP-1)

Effective date: 2026-07-26

## Threshold

The Threshold applicable to Rodriguez Partners is USD 340,000.

## Minimum Transfer Amount

The Minimum Transfer Amount (MTA) applicable to Rodriguez Partners is USD 11,000.
"""


class TestChunkMarkdown:
    def test_splits_preamble_and_each_header_into_separate_chunks(self) -> None:
        chunks = chunk_markdown(SAMPLE_DOC)

        assert len(chunks) == 3
        assert chunks[0].section == "Overview"
        assert "Rodriguez Partners" in chunks[0].text
        assert "Effective date" in chunks[0].text
        assert chunks[1].section == "Threshold"
        assert "USD 340,000" in chunks[1].text
        assert chunks[2].section == "Minimum Transfer Amount"
        assert "USD 11,000" in chunks[2].text

    def test_each_chunk_contains_only_its_own_section(self) -> None:
        chunks = chunk_markdown(SAMPLE_DOC)

        assert "340,000" not in chunks[2].text
        assert "11,000" not in chunks[1].text

    def test_document_with_no_headers_becomes_a_single_chunk(self) -> None:
        chunks = chunk_markdown("Just a plain paragraph, no headers at all.")

        assert len(chunks) == 1
        assert chunks[0].section == "Overview"

    def test_custom_preamble_section_name(self) -> None:
        chunks = chunk_markdown(SAMPLE_DOC, preamble_section="Title")

        assert chunks[0].section == "Title"

    def test_empty_preamble_is_not_emitted_as_a_chunk(self) -> None:
        chunks = chunk_markdown("## Only Section\n\nSome content.")

        assert len(chunks) == 1
        assert chunks[0].section == "Only Section"


class TestExtractEffectiveDate:
    def test_extracts_date_when_present(self) -> None:
        assert extract_effective_date(SAMPLE_DOC) == "2026-07-26"

    def test_returns_empty_string_when_absent(self) -> None:
        assert extract_effective_date("# Margin Policy\n\nNo date here.") == ""
