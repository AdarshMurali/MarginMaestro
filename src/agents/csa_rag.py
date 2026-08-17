from openai import OpenAI
from pydantic import BaseModel

from config.settings import Settings, get_settings
from persistence.models import RatingTrigger
from rag.models import Citation, CSATermsResult
from rag.retriever import RetrievedChunk, retrieve

DEFAULT_TOP_K = 10

SYSTEM_PROMPT = (
    "You extract structured Credit Support Annex (CSA) terms from the provided "
    "document excerpts for one counterparty. Only use information present in the "
    "excerpts -- never infer, estimate, or use outside knowledge. If a field "
    'cannot be determined from the excerpts, use 0 for numeric fields, "USD" for '
    "currency, and an empty list for list fields. Express each haircut as a "
    'decimal fraction, not a percentage number -- a haircut written as "8%" in '
    "the text must be returned as 0.08, not 8. For rating_triggers, extract one "
    "entry per rating-trigger clause found: below_grade is the credit rating "
    "(one of AAA, AA, A, BBB, BB, B, CCC, D) below which the clause applies, "
    "and reduced_threshold is the numeric Threshold value the clause states "
    "applies once triggered. Only extract a trigger if the clause states a "
    "concrete resulting Threshold number -- do not invent one."
)


class CSATermsUnavailableError(Exception):
    """Raised when no CSA chunks can be retrieved, or the LLM can't extract terms."""


class _HaircutEntry(BaseModel):
    collateral_type: str
    haircut: float


class _CSATermsExtraction(BaseModel):
    """LLM-facing extraction schema. `haircuts` is a list of entries, not a
    dict -- OpenAI's structured-output mode rejects open-ended dict/
    additionalProperties schemas (must be a fixed, enumerable shape).
    """

    threshold: float
    mta: float
    currency: str
    eligible_collateral: list[str]
    haircuts: list[_HaircutEntry]
    rating_triggers: list[RatingTrigger]


def _build_context(chunks: list[RetrievedChunk]) -> str:
    return "\n\n".join(f"[{chunk.section}]\n{chunk.text}" for chunk in chunks)


def answer_csa_terms(
    counterparty_id: str,
    question: str | None = None,
    top_k: int = DEFAULT_TOP_K,
    openai_client: OpenAI | None = None,
    settings: Settings | None = None,
) -> CSATermsResult:
    """Retrieves that counterparty's CSA chunks (MM-25) and asks the LLM to
    extract structured terms, grounded strictly in the retrieved excerpts.
    Citations are the retrieved chunks themselves, not LLM self-reporting --
    more reliable and matches what was actually consulted.
    """
    settings = settings or get_settings()
    question = question or (
        f"What are {counterparty_id}'s CSA terms -- threshold, minimum transfer "
        "amount, eligible collateral, haircuts, and rating triggers?"
    )

    chunks = retrieve(question, counterparty_id=counterparty_id, doc_type="csa", top_k=top_k)
    if not chunks:
        raise CSATermsUnavailableError(f"No CSA document chunks found for {counterparty_id}")

    openai_client = openai_client or OpenAI(api_key=settings.openai_api_key)
    completion = openai_client.chat.completions.parse(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"{question}\n\n---\n\n{_build_context(chunks)}"},
        ],
        response_format=_CSATermsExtraction,
    )
    extraction = completion.choices[0].message.parsed
    if extraction is None:
        raise CSATermsUnavailableError(
            f"LLM could not extract structured CSA terms for {counterparty_id}"
        )

    return CSATermsResult(
        counterparty_id=counterparty_id,
        threshold=extraction.threshold,
        mta=extraction.mta,
        currency=extraction.currency,
        eligible_collateral=extraction.eligible_collateral,
        haircuts={entry.collateral_type: entry.haircut for entry in extraction.haircuts},
        rating_triggers=extraction.rating_triggers,
        citations=[Citation(source_file=c.source_file, section=c.section) for c in chunks],
    )
