"""The personalised margin-call notice as a PDF (MM-144, ADR-0016 amendment
2026-10-06), sent as the document header of the `margin_call_notice_v2`
WhatsApp template when WHATSAPP_NOTICE_PDF=on.

Every figure is the calculation's own, formatted here by code (CLAUDE.md
golden rule 1, ADR-0005):

1. **Header:** reference, counterparty, amount, deadline -- the same four
   values the template's body quotes.
2. **Covering paragraph:** the only model-written text. Gemini drafts it
   with placeholders only (`{REFERENCE}`, `{CALL_AMOUNT}`, ...); code
   rejects a draft with any digit or unknown placeholder (one retry), fills
   the values in, and the guardrail pipeline screens the prompt and the
   answer (GuardedLLM, fail closed). The model never sees a figure, a name,
   a date or a phone number.
3. **How this call was calculated:** portfolio value today and at the prior
   close, variation margin, initial margin, exposure, collateral held after
   haircuts (per type), the threshold after rating triggers, the MTA and the
   call -- from the state the breach check wrote -- plus the market move
   behind an intraday call (MM-125's event impact) and the largest positions.
4. **Your CSA terms:** threshold, MTA, eligible collateral and haircuts and
   rating triggers, as the CSA RAG step extracted them (reused from the
   state, not re-asked), with section citations; and the rounding,
   settlement-timing and dispute-resolution clauses quoted verbatim from the
   counterparty's CSA (one extra retrieval -- an embedding, no LLM call).

**Failure is loud.** Anything that stops the PDF being built -- retrieval,
an unusable draft, a guardrail block -- raises. The orchestrator records the
notice as failed and the call escalates (ADR-0016: no silent fallback; the
v1 template is *not* sent instead, because the approved call is meant to go
out with its explanation, and a person should decide what happens next).

Every page carries the synthetic-data label. No phone number is ever an
input here.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from adapters.factory import get_llm
from agents.communication import draft_with_placeholders, format_deadline, money
from agents.pdf_writer import PdfDocument
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
from ports.llm import LLMClient
from rag.models import Citation
from rag.retriever import RetrievedChunk, retrieve

SYNTHETIC_LABEL = "(Test message - synthetic data)"
TOP_POSITIONS = 5
EXTRA_CLAUSES = {
    "rounding": ("Rounding",),
    "settlement": ("Settlement Timing", "Settlement", "Transfer Timing"),
    "dispute": ("Dispute Resolution", "Disputes", "Dispute"),
}
CLAUSE_TITLES = {
    "rounding": "Rounding",
    "settlement": "Settlement timing",
    "dispute": "Dispute process",
}
EXTRA_CLAUSE_QUERY = "rounding of delivery amounts, settlement timing and dispute resolution"

COVER_SYSTEM_PROMPT = (
    "You write the covering paragraph of a formal margin call notice that a bank "
    "sends to a counterparty as a PDF. You are never given figures, names or dates: "
    "write the placeholders you are given (for example {CALL_AMOUNT}) exactly as "
    "written wherever that value belongs; they are filled in afterwards. Never write "
    "any digits. One paragraph of two to four sentences, plain text, no markdown, no "
    "greeting, no sign-off, no subject line. Do not invent terms, deadlines, "
    "consequences or contact details."
)
COVER_REQUEST = (
    "Write the covering paragraph. Placeholders: {COUNTERPARTY} (the counterparty), "
    "{REFERENCE} (the margin call reference), {CALL_AMOUNT} (the amount called, with "
    "currency) and {DEADLINE} (when the collateral must be received). Say that this "
    "notice sets out how the call was calculated and the CSA terms that apply, ask the "
    "counterparty to transfer eligible collateral by {DEADLINE}, and to confirm receipt "
    "with the Acknowledge button on the WhatsApp message. {REFERENCE}, {CALL_AMOUNT} and "
    "{DEADLINE} must appear."
)


class NoticePdfError(Exception):
    """The PDF notice can't be built; the call escalates instead of sending."""


class CsaClause(BaseModel):
    section: str
    text: str
    source_file: str


class NoticePdfInputs(BaseModel):
    """Everything the PDF shows, all computed by code before this module."""

    reference: str
    counterparty_id: str
    counterparty_name: str  # display name, with the synthetic-data label in the demo
    currency: str
    amount_called: float
    computed_call: float
    deadline: str  # communication.format_deadline
    issued_at: datetime
    variation_margin: VariationMargin
    initial_margin: InitialMargin
    collateral_lines: list[CollateralLine] = Field(default_factory=list)
    collateral_held: float
    csa_terms: CSATerms
    effective_threshold: float
    csa_collateral: dict[str, float] = Field(default_factory=dict)  # eligible -> haircut
    citations: list[Citation] = Field(default_factory=list)
    price_moves: list[PriceMove] = Field(default_factory=list)
    event_impact: EventImpact | None = None
    positions: list[PositionMTM] = Field(default_factory=list)
    rationale: str | None = None


def document_filename(reference: str) -> str:
    return f"{reference}.pdf"


# --- the model-written part: placeholders only ------------------------------------


def draft_covering_paragraph(inputs: NoticePdfInputs, llm: LLMClient) -> str:
    """Gemini drafts around placeholders; code validates and fills them
    (communication.draft_with_placeholders, MM-116). Raises
    NoticeDraftingError on an unusable draft and GuardrailError on a block."""
    values = {
        "COUNTERPARTY": inputs.counterparty_name,
        "REFERENCE": inputs.reference,
        "CALL_AMOUNT": money(inputs.amount_called, inputs.currency),
        "DEADLINE": inputs.deadline,
    }
    return draft_with_placeholders(
        llm,
        COVER_REQUEST,
        values,
        {"REFERENCE", "CALL_AMOUNT", "DEADLINE"},
        f"PDF covering paragraph for {inputs.counterparty_id}",
        system_prompt=COVER_SYSTEM_PROMPT,
    )


# --- the CSA clauses the extraction doesn't cover ----------------------------------


def csa_extra_clauses(chunks: list[RetrievedChunk]) -> dict[str, CsaClause]:
    """Rounding, settlement timing and dispute resolution, quoted verbatim
    from the counterparty's own retrieved CSA chunks (`rag.retriever`
    RetrievedChunk). A clause the CSA doesn't have is simply absent."""
    found: dict[str, CsaClause] = {}
    for chunk in chunks:
        for key, sections in EXTRA_CLAUSES.items():
            if key in found or chunk.section.strip().lower() not in {s.lower() for s in sections}:
                continue
            found[key] = CsaClause(
                section=chunk.section,
                text=_strip_heading(chunk.text),
                source_file=chunk.source_file,
            )
    return found


def retrieve_extra_clauses(counterparty_id: str, settings: Settings) -> dict[str, CsaClause]:
    """One retrieval over the counterparty's CSA (an embedding call; no LLM).
    Fails loud (NoticePdfError) if the store can't be read."""
    try:
        chunks = retrieve(
            EXTRA_CLAUSE_QUERY,
            counterparty_id=counterparty_id,
            doc_type="csa",
            top_k=12,
            settings=settings,
        )
    except Exception as exc:  # any store/embedding failure: the PDF can't be built
        raise NoticePdfError(f"CSA clauses could not be retrieved ({type(exc).__name__})") from exc
    return csa_extra_clauses([c for c in chunks if c.counterparty_id == counterparty_id])


def _strip_heading(text: str) -> str:
    lines = text.strip().splitlines()
    if lines and lines[0].startswith("#"):
        lines = lines[1:]
    return " ".join(line.strip() for line in lines if line.strip())


# --- the document -------------------------------------------------------------------


def _pct(fraction: float) -> str:
    return f"{fraction:.1%}" if round(fraction * 100, 1) % 1 else f"{fraction:.0%}"


def _breakdown_rows(inputs: NoticePdfInputs) -> list[tuple[str, str]]:
    c = inputs.currency
    vm, im = inputs.variation_margin, inputs.initial_margin
    exposure = vm.variation_margin + im.initial_margin
    rows = [
        ("Portfolio value today (mark-to-market)", money(vm.mtm_today, c)),
        ("Portfolio value at the prior close", money(vm.mtm_prior, c)),
        ("Variation margin (change since the prior close)", money(vm.variation_margin, c)),
        (
            f"Initial margin (VIX {im.vix_level:.2f}, multiplier {im.vix_multiplier:.2f}x)",
            money(im.initial_margin, c),
        ),
        ("Exposure (variation margin + initial margin)", money(exposure, c)),
        ("Threshold (after any rating trigger)", money(inputs.effective_threshold, c)),
        ("Collateral held, after haircuts", money(inputs.collateral_held, c)),
        ("Minimum transfer amount", money(inputs.csa_terms.mta, c)),
        (
            "Call amount (exposure - threshold - collateral held, at least the MTA)",
            money(inputs.computed_call, c),
        ),
    ]
    if abs(inputs.amount_called - inputs.computed_call) > 0.005:
        rows.append(("Amount called, as adjusted by the approver", money(inputs.amount_called, c)))
    return rows


def _cite(citations: list[Citation], *sections: str) -> str:
    wanted = {s.lower() for s in sections}
    hits = sorted(
        {
            f"{c.source_file}, section '{c.section}'"
            for c in citations
            if c.section.lower() in wanted
        }
    )
    return f"Source: {'; '.join(hits)}" if hits else "Source: your CSA (section not retrieved)"


def build_notice_pdf(
    inputs: NoticePdfInputs, covering_paragraph: str, clauses: dict[str, CsaClause]
) -> bytes:
    """Lays the notice out (agents.pdf_writer). Pure: no I/O, no model."""
    c = inputs.currency
    doc = PdfDocument(
        title=f"Margin call {inputs.reference}",
        footer=f"{SYNTHETIC_LABEL}  |  Margin call {inputs.reference}",
    )
    doc.paragraph(SYNTHETIC_LABEL, size=9, bold=True)
    doc.space(4)
    doc.paragraph(f"Margin call notice {inputs.reference}", size=18, bold=True)
    doc.space(6)
    doc.figures(
        [
            ("Counterparty", f"{inputs.counterparty_name} ({inputs.counterparty_id})"),
            ("Reference", inputs.reference),
            ("Amount called", money(inputs.amount_called, c)),
            ("Collateral to be received by", inputs.deadline),
            ("Issued", format_deadline(inputs.issued_at)),
        ]
    )
    doc.rule()
    doc.paragraph(covering_paragraph)

    doc.heading("How this call was calculated")
    doc.figures(_breakdown_rows(inputs), bold_last=True)
    if inputs.collateral_lines:
        doc.space(6)
        doc.paragraph("Collateral held", bold=True)
        doc.figures(
            [
                (
                    (
                        f"{line.collateral_type}: {money(line.value, c)} less a "
                        f"{_pct(line.haircut_pct)} haircut"
                    ),
                    money(line.value_after_haircut, c),
                )
                for line in inputs.collateral_lines
            ]
        )
    if inputs.price_moves:
        doc.space(6)
        doc.paragraph("The market move behind this call", bold=True)
        rows = [
            (
                f"{m.ticker}: {money(m.from_price, c)} to {money(m.to_price, c)}",
                f"{(m.to_price / m.from_price - 1):+.2%}",
            )
            for m in inputs.price_moves
        ]
        if inputs.event_impact is not None:
            impact = inputs.event_impact
            rows += [
                ("Its effect on your portfolio value", money(impact.mtm_change, c)),
                ("Its effect on initial margin", money(impact.im_change, c)),
                ("Its effect on exposure", money(impact.exposure_change, c)),
            ]
        doc.figures(rows)
    if inputs.positions:
        doc.space(6)
        doc.paragraph("Largest positions by current value", bold=True)
        largest = sorted(inputs.positions, key=lambda p: abs(p.mtm), reverse=True)
        doc.figures(
            [
                (f"{p.ticker}: {p.quantity:,.0f} at {money(p.price, c)}", money(p.mtm, c))
                for p in largest[:TOP_POSITIONS]
            ]
        )
    if inputs.rationale:
        doc.space(6)
        doc.paragraph(inputs.rationale, size=9)

    doc.heading("Your CSA terms")
    terms = inputs.csa_terms
    doc.figures(
        [
            ("Threshold", money(terms.threshold, terms.currency)),
            ("Minimum transfer amount", money(terms.mta, terms.currency)),
        ]
    )
    doc.paragraph(_cite(inputs.citations, "Threshold", "Minimum Transfer Amount"), size=8, indent=0)
    if inputs.csa_collateral:
        doc.space(4)
        doc.paragraph("Eligible collateral and haircuts", bold=True)
        doc.figures(
            [(name, f"{_pct(haircut)} haircut") for name, haircut in inputs.csa_collateral.items()]
        )
        doc.paragraph(_cite(inputs.citations, "Eligible Collateral"), size=8)
    for trigger in terms.rating_triggers:
        doc.paragraph(
            f"Rating trigger: if your credit rating falls below {trigger.below_grade}, the "
            f"threshold becomes {money(trigger.reduced_threshold, terms.currency)}."
        )
    if terms.rating_triggers:
        doc.paragraph(_cite(inputs.citations, "Rating Triggers"), size=8)
    for key, title in CLAUSE_TITLES.items():
        doc.space(4)
        doc.paragraph(title, bold=True)
        clause = clauses.get(key)
        if clause is None:
            doc.paragraph("Not stated in the CSA on file. Please contact us before the deadline.")
            continue
        doc.paragraph(clause.text)
        doc.paragraph(f"Source: {clause.source_file}, section '{clause.section}'", size=8)

    doc.space(10)
    doc.rule()
    doc.paragraph(
        "All figures in this notice were calculated by our margin system from your "
        "positions, market prices and your CSA; none was written by an AI model. "
        f"{SYNTHETIC_LABEL}",
        size=8,
    )
    return doc.render()


def prepare_notice_pdf(
    inputs: NoticePdfInputs,
    settings: Settings,
    *,
    llm: LLMClient | None = None,
    clauses: dict[str, CsaClause] | None = None,
) -> tuple[bytes, str]:
    """The finished PDF and its file name. Raises NoticePdfError,
    NoticeDraftingError or GuardrailError; the caller escalates the call."""
    if clauses is None:
        clauses = retrieve_extra_clauses(inputs.counterparty_id, settings)
    covering = draft_covering_paragraph(inputs, llm or get_llm(settings))
    return build_notice_pdf(inputs, covering, clauses), document_filename(inputs.reference)
