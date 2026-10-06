"""MM-144: the personalised PDF notice. Every figure comes from the
calculation; the model writes one covering paragraph around placeholders
(mocked here), which code validates and fills; the CSA terms carry their
section citations; every page is labelled synthetic; no phone number ever
appears."""

import re
from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from agents import notice_pdf
from agents.communication import NoticeDraftingError
from agents.notice_pdf import (
    COVER_SYSTEM_PROMPT,
    SYNTHETIC_LABEL,
    CsaClause,
    NoticePdfError,
    NoticePdfInputs,
    csa_extra_clauses,
    document_filename,
    prepare_notice_pdf,
    retrieve_extra_clauses,
)
from agents.pdf_writer import PdfDocument, text_width, wrap
from calc.models import (
    CollateralLine,
    CSATerms,
    EventImpact,
    InitialMargin,
    PositionMTM,
    PriceMove,
    VariationMargin,
)
from config.settings import Settings
from persistence.models import AssetClass, RatingGrade, RatingTrigger
from ports.guardrail import GuardrailBlocked, Verdict
from rag.models import Citation
from rag.retriever import RetrievedChunk

COVER = (
    "Please find enclosed margin call {REFERENCE} for {COUNTERPARTY}. It sets out how "
    "the call of {CALL_AMOUNT} was calculated and the CSA terms that apply. Please "
    "transfer eligible collateral by {DEADLINE} and tap Acknowledge on the WhatsApp message."
)


class ScriptedLLM:
    def __init__(self, *drafts: str | None) -> None:
        self._drafts = list(drafts)
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> str | None:
        self.calls.append((system, user))
        return self._drafts.pop(0)

    def parse(self, system, user, schema):  # pragma: no cover - not used
        raise NotImplementedError


class BlockingLLM:
    def complete(self, system: str, user: str) -> str | None:
        raise GuardrailBlocked(
            "response", Verdict(allowed=False, guardrail="model_armor", reasons=["jailbreak"])
        )

    def parse(self, system, user, schema):  # pragma: no cover - not used
        raise NotImplementedError


def _inputs(**overrides) -> NoticePdfInputs:
    values = {
        "reference": "MC-1A2B3C4D",
        "counterparty_id": "CP-1",
        "counterparty_name": "Rodriguez Partners (TEST)",
        "currency": "USD",
        "amount_called": 1_234_567.89,
        "computed_call": 1_234_567.89,
        "deadline": "17:00 UTC on 6 October 2026",
        "issued_at": datetime(2026, 10, 6, 16, 0, tzinfo=UTC),
        "variation_margin": VariationMargin(
            portfolio_id="PF-CP-1",
            mtm_today=5_400_000.0,
            mtm_prior=4_000_000.0,
            variation_margin=1_400_000.0,
        ),
        "initial_margin": InitialMargin(
            portfolio_id="PF-CP-1", vix_level=21.5, vix_multiplier=1.08, initial_margin=310_000.0
        ),
        "collateral_lines": [
            CollateralLine(
                collateral_type="cash", value=100_000.0, haircut_pct=0.0, value_after_haircut=100e3
            ),
            CollateralLine(
                collateral_type="bond",
                value=50_000.0,
                haircut_pct=0.08,
                value_after_haircut=46_000.0,
            ),
        ],
        "collateral_held": 146_000.0,
        "csa_terms": CSATerms(
            threshold=340_000.0,
            mta=11_000.0,
            currency="USD",
            rating_triggers=[RatingTrigger(below_grade=RatingGrade.B, reduced_threshold=0.0)],
        ),
        "effective_threshold": 329_432.11,
        "csa_collateral": {"Cash (USD)": 0.0, "US Treasury securities": 0.025},
        "citations": [
            Citation(source_file="csa/CP-1.md", section="Threshold"),
            Citation(source_file="csa/CP-1.md", section="Minimum Transfer Amount"),
            Citation(source_file="csa/CP-1.md", section="Eligible Collateral"),
            Citation(source_file="csa/CP-1.md", section="Rating Triggers"),
        ],
        "price_moves": [PriceMove(ticker="TSLA", from_price=250.0, to_price=280.0)],
        "event_impact": EventImpact(
            tickers=["TSLA"], mtm_change=300_000.0, im_change=25_000.0, exposure_change=325_000.0
        ),
        "positions": [
            PositionMTM(
                position_id=f"P{i}",
                ticker=t,
                asset_class=AssetClass.EQUITY,
                quantity=q,
                price=p,
                mtm=q * p,
            )
            for i, (t, q, p) in enumerate(
                [
                    ("TSLA", 10_000, 280.0),
                    ("AAPL", 5_000, 200.0),
                    ("MSFT", 1_000, 400.0),
                    ("NVDA", 100, 900.0),
                    ("JPM", 50, 150.0),
                    ("XOM", 10, 100.0),
                ]
            )
        ],
        "rationale": "The TSLA move increased your exposure.",
    }
    values.update(overrides)
    return NoticePdfInputs(**values)


CLAUSES = {
    "rounding": CsaClause(
        section="Rounding", text="Delivery Amounts are not rounded.", source_file="csa/CP-1.md"
    ),
    "settlement": CsaClause(
        section="Settlement Timing",
        text="Collateral must be received by the deadline.",
        source_file="csa/CP-1.md",
    ),
    "dispute": CsaClause(
        section="Dispute Resolution",
        text="Notify the Valuation Agent before the deadline.",
        source_file="csa/CP-1.md",
    ),
}


def pdf_lines(pdf: bytes) -> list[str]:
    """The text-showing strings of our own (uncompressed) PDF, unescaped."""

    def unescape(match: re.Match[bytes]) -> bytes:
        token = match.group(1)
        return bytes([int(token, 8)]) if len(token) == 3 else token

    return [
        re.sub(rb"\\([0-7]{3}|.)", unescape, m.group(1)).decode("cp1252")
        for m in re.finditer(rb"\(((?:\\.|[^\\)])*)\) Tj", pdf)
    ]


def pdf_text(pdf: bytes) -> str:
    return "\n".join(pdf_lines(pdf))


def _pdf(**overrides) -> bytes:
    pdf, _ = prepare_notice_pdf(
        _inputs(**overrides), Settings(_env_file=None), llm=ScriptedLLM(COVER), clauses=CLAUSES
    )
    return pdf


# --- content -----------------------------------------------------------------------


def test_header_quotes_the_four_template_values():
    text = pdf_text(_pdf())

    assert "Margin call notice MC-1A2B3C4D" in text
    assert "Rodriguez Partners (TEST) (CP-1)" in text
    assert "USD 1,234,567.89" in text
    assert "17:00 UTC on 6 October 2026" in text
    assert "16:00 UTC on 6 October 2026" in text  # issued


def test_breakdown_shows_the_calculations_own_figures():
    text = pdf_text(_pdf())

    for figure in (
        "USD 5,400,000.00",  # MTM today
        "USD 4,000,000.00",  # prior close
        "USD 1,400,000.00",  # VM
        "USD 310,000.00",  # IM
        "USD 1,710,000.00",  # exposure = VM + IM, computed here by code
        "USD 329,432.11",  # threshold after the rating trigger
        "USD 146,000.00",  # collateral held after haircuts
        "USD 11,000.00",  # MTA
        "USD 46,000.00",  # bond after its 8% haircut
        "USD 325,000.00",  # the event's exposure change
    ):
        assert figure in text, figure
    assert "VIX 21.50, multiplier 1.08x" in text
    assert "bond: USD 50,000.00 less a 8% haircut" in text
    assert "TSLA: USD 250.00 to USD 280.00" in text and "+12.00%" in text
    assert "The TSLA move increased your exposure." in text


def test_only_the_five_largest_positions_are_listed():
    text = pdf_text(_pdf())

    assert "TSLA: 10,000 at USD 280.00" in text
    assert "JPM: 50 at USD 150.00" in text
    assert "XOM" not in text


def test_an_adjusted_amount_is_shown_next_to_the_computed_one():
    text = pdf_text(_pdf(amount_called=1_000_000.0))

    assert "Amount called, as adjusted by the approver" in text
    assert "USD 1,000,000.00" in text and "USD 1,234,567.89" in text


def test_csa_terms_carry_section_citations_and_quoted_clauses():
    text = pdf_text(_pdf())

    assert "USD 340,000.00" in text  # contractual threshold
    assert "Source: csa/CP-1.md, section 'Minimum Transfer Amount'; csa/CP-1.md" in text
    assert "Source: csa/CP-1.md, section 'Eligible Collateral'" in text
    assert "Source: csa/CP-1.md, section 'Rating Triggers'" in text
    assert "US Treasury securities" in text and "2.5% haircut" in text
    assert "falls below B, the threshold becomes USD 0.00" in text
    assert "Delivery Amounts are not rounded." in text
    assert "Source: csa/CP-1.md, section 'Settlement Timing'" in text
    assert "Source: csa/CP-1.md, section 'Dispute Resolution'" in text


def test_missing_clauses_and_citations_say_so_instead_of_inventing_terms():
    pdf, _ = prepare_notice_pdf(
        _inputs(citations=[], csa_collateral={}, price_moves=[], event_impact=None, positions=[]),
        Settings(_env_file=None),
        llm=ScriptedLLM(COVER),
        clauses={},
    )
    text = pdf_text(pdf)

    assert text.count("Not stated in the CSA on file") == 3
    assert "Source: your CSA (section not retrieved)" in text
    assert "market move" not in text and "Largest positions" not in text


def test_every_page_is_labelled_synthetic_and_numbered():
    pdf = _pdf()
    lines = pdf_lines(pdf)
    pages = int(re.search(rb"/Type /Pages /Kids \[[^\]]*\] /Count (\d+)", pdf).group(1))

    footers = [line for line in lines if line.startswith(SYNTHETIC_LABEL) and "page" in line]
    assert len(footers) == pages
    assert footers[-1].endswith(f"page {pages} of {pages}")
    assert lines[0] == SYNTHETIC_LABEL


def test_no_phone_number_ever_appears():
    pdf = _pdf()

    assert not re.search(rb"\+\d{8,15}", pdf)
    assert not re.search(r"\+\d{8,15}", pdf_text(pdf))


def test_covering_paragraph_is_filled_by_code_from_placeholders():
    llm = ScriptedLLM(COVER)

    prepare_notice_pdf(_inputs(), Settings(_env_file=None), llm=llm, clauses=CLAUSES)

    system, request = llm.calls[0]
    assert system == COVER_SYSTEM_PROMPT
    # The model saw placeholders only: no figure, name, date or reference.
    for value in ("1,234,567", "Rodriguez", "October", "MC-1A2B3C4D", "CP-1"):
        assert value not in request
    assert "{CALL_AMOUNT}" in request


def test_a_draft_with_figures_is_retried_then_fails_loud():
    llm = ScriptedLLM(COVER.replace("{CALL_AMOUNT}", "USD 2,000,000"), "no placeholders")

    with pytest.raises(NoticeDraftingError, match="Unusable PDF covering paragraph"):
        prepare_notice_pdf(_inputs(), Settings(_env_file=None), llm=llm, clauses=CLAUSES)
    assert "rejected" in llm.calls[1][1]


def test_a_guardrail_block_propagates():
    with pytest.raises(GuardrailBlocked):
        prepare_notice_pdf(_inputs(), Settings(_env_file=None), llm=BlockingLLM(), clauses=CLAUSES)


def test_the_configured_llm_is_used_by_default():
    llm = ScriptedLLM(COVER)
    with patch("agents.notice_pdf.get_llm", return_value=llm) as get_llm:
        prepare_notice_pdf(_inputs(), Settings(_env_file=None), clauses=CLAUSES)

    get_llm.assert_called_once()
    assert llm.calls


def test_filename_is_the_reference():
    assert document_filename("MC-1A2B3C4D") == "MC-1A2B3C4D.pdf"


# --- the extra CSA clauses ---------------------------------------------------------


def _chunk(section: str, text: str, counterparty: str = "CP-1") -> RetrievedChunk:
    return RetrievedChunk(
        text=f"## {section}\n\n{text}",
        source_file=f"csa/{counterparty}.md",
        doc_type="csa",
        counterparty_id=counterparty,
        effective_date="2026-08-16",
        section=section,
        distance=0.1,
    )


def test_extra_clauses_are_quoted_verbatim_by_section():
    clauses = csa_extra_clauses(
        [
            _chunk("Threshold", "USD 340,000."),
            _chunk("Rounding", "Not rounded,\nto the cent."),
            _chunk("Settlement Timing", "By the deadline."),
            _chunk("Dispute Resolution", "Notify us."),
        ]
    )

    assert set(clauses) == {"rounding", "settlement", "dispute"}
    assert clauses["rounding"].text == "Not rounded, to the cent."
    assert clauses["dispute"].source_file == "csa/CP-1.md"


def test_retrieval_keeps_only_the_counterpartys_own_csa():
    chunks = [_chunk("Rounding", "Other book.", counterparty="CP-2"), _chunk("Rounding", "Ours.")]
    with patch("agents.notice_pdf.retrieve", return_value=chunks) as retrieve:
        clauses = retrieve_extra_clauses("CP-1", Settings(_env_file=None))

    assert clauses["rounding"].text == "Ours."
    assert retrieve.call_args.kwargs["counterparty_id"] == "CP-1"
    assert retrieve.call_args.kwargs["doc_type"] == "csa"


def test_retrieval_failure_fails_loud():
    with (
        patch("agents.notice_pdf.retrieve", side_effect=ConnectionError("store down")),
        pytest.raises(NoticePdfError, match="ConnectionError"),
    ):
        retrieve_extra_clauses("CP-1", Settings(_env_file=None))


def test_prepare_retrieves_clauses_when_not_given():
    with patch.object(notice_pdf, "retrieve", return_value=[_chunk("Rounding", "Exact.")]):
        pdf, name = prepare_notice_pdf(_inputs(), Settings(_env_file=None), llm=ScriptedLLM(COVER))

    assert "Exact." in pdf_text(pdf) and name == "MC-1A2B3C4D.pdf"


# --- the writer ----------------------------------------------------------------------


def test_file_structure_xref_offsets_point_at_their_objects():
    pdf = _pdf()

    assert pdf.startswith(b"%PDF-1.4") and pdf.rstrip().endswith(b"%%EOF")
    startxref = int(re.search(rb"startxref\n(\d+)\n", pdf).group(1))
    assert pdf[startxref:].startswith(b"xref")
    entries = re.findall(rb"(\d{10}) 00000 n ", pdf[startxref:])
    for number, offset in enumerate(entries, start=1):
        assert pdf[int(offset) :].startswith(b"%d 0 obj" % number)
    for match in re.finditer(rb"<< /Length (\d+) >>\nstream\n", pdf):
        end = match.end() + int(match.group(1))
        assert pdf[end : end + 10] == b"\nendstream"


def test_long_documents_flow_onto_new_pages_with_escaped_text():
    doc = PdfDocument(title="T (x)", footer="footer")
    for _ in range(120):
        doc.paragraph("A line with (parentheses), a back\\slash and a pound sign £.")
    pdf = doc.render()

    assert int(re.search(rb"/Count (\d+)", pdf).group(1)) >= 3
    assert rb"\(parentheses\)" in pdf and rb"back\\slash" in pdf and rb"\243" in pdf
    assert "A line with (parentheses), a back\\slash and a pound sign £." in pdf_lines(pdf)


def test_wrap_breaks_lines_and_overlong_words_within_the_width():
    lines = wrap("word " * 50 + "x" * 200, 10, 200)

    assert len(lines) > 3
    assert all(text_width(line, 10) <= 200 for line in lines)
    assert wrap("", 10, 100) == [""]
    assert text_width("€", 10) > 0
