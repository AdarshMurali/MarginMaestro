"""Reconciliation & Dispute Agent (MM-47, docs/AGENTS.md #4): isolates
trade-level breaks (MM-46, deterministic) and, only when a genuine
disagreement exists, drafts a suggested resolution grounded in retrieved
exception-rules + historical dispute precedent (RAG). The numeric diff is
deterministic; the LLM only explains/suggests (AGENTS.md's Notes line).
Standalone capability this phase -- not wired into the live orchestrator
graph (confirmed with the user before MM-46 started)."""

from openai import OpenAI
from pydantic import BaseModel

from calc.trade_diff import BreakItem, reconcile
from config.settings import Settings, get_settings
from persistence.models import Position
from rag.models import Citation
from rag.retriever import RetrievedChunk, retrieve

DEFAULT_TOP_K = 5

SYSTEM_PROMPT = (
    "You are a margin operations reconciliation assistant. Given isolated "
    "trade breaks and retrieved exception-rules/precedent excerpts, draft a "
    "concise suggested resolution grounded strictly in the retrieved "
    "excerpts -- never invent a rule or precedent not present in the "
    "excerpts. If no excerpt clearly applies, say the break needs manual "
    "operations review rather than guessing."
)


class ReconciliationAgentResult(BaseModel):
    agreed: bool
    break_items: list[BreakItem]
    suggested_resolution: str | None
    citations: list[Citation]


def _build_break_summary(break_items: list[BreakItem]) -> str:
    return "\n".join(
        f"- {b.ticker}: {b.break_type.value} "
        f"(ours={b.our_quantity}, counterparty={b.counterparty_quantity})"
        for b in break_items
    )


def _build_context(chunks: list[RetrievedChunk]) -> str:
    return "\n\n".join(f"[{chunk.doc_type}: {chunk.section}]\n{chunk.text}" for chunk in chunks)


def draft_resolution(
    break_items: list[BreakItem],
    top_k: int = DEFAULT_TOP_K,
    openai_client: OpenAI | None = None,
    settings: Settings | None = None,
) -> tuple[str, list[Citation]]:
    settings = settings or get_settings()
    break_summary = _build_break_summary(break_items)
    query = f"How should these margin call breaks be resolved?\n{break_summary}"

    chunks = retrieve(query, doc_type="exceptions", top_k=top_k, settings=settings) + retrieve(
        query, doc_type="disputes", top_k=top_k, settings=settings
    )

    openai_client = openai_client or OpenAI(api_key=settings.openai_api_key)
    completion = openai_client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Breaks:\n{break_summary}\n\n---\n\n{_build_context(chunks)}",
            },
        ],
    )
    text = completion.choices[0].message.content
    resolution = text.strip() if text else "No resolution could be drafted; manual review required."
    citations = [Citation(source_file=c.source_file, section=c.section) for c in chunks]
    return resolution, citations


def reconcile_call(
    our_positions: list[Position],
    counterparty_positions: list[Position],
    our_total: float,
    counterparty_total: float,
    tolerance: float,
    openai_client: OpenAI | None = None,
    settings: Settings | None = None,
) -> ReconciliationAgentResult:
    """Full Reconciliation Agent flow: MM-46's deterministic gate first: if
    within tolerance, no LLM call is made at all -- there's nothing to
    explain."""
    diff_result = reconcile(
        our_positions, counterparty_positions, our_total, counterparty_total, tolerance
    )
    if diff_result.agreed:
        return ReconciliationAgentResult(
            agreed=True, break_items=[], suggested_resolution=None, citations=[]
        )

    resolution, citations = draft_resolution(
        diff_result.break_items, openai_client=openai_client, settings=settings
    )
    return ReconciliationAgentResult(
        agreed=False,
        break_items=diff_result.break_items,
        suggested_resolution=resolution,
        citations=citations,
    )
