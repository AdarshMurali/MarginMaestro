import argparse
import random
from datetime import UTC, date, datetime
from pathlib import Path

from persistence.generators.counterparties import generate_counterparties
from persistence.models import RatingGrade, RatingTrigger
from rag.models import CSATermsDocument

DEFAULT_SEED = 42
DEFAULT_OUTPUT_DIR = Path("data/documents")

COLLATERAL_HAIRCUTS = {
    "Cash (USD)": 0.0,
    "US Treasury securities": 0.02,
    "Investment-grade corporate bonds": 0.08,
    "Money market fund shares": 0.01,
}

# Grades drawn from the same RatingGrade enum actually stored per counterparty
# (RatingORM) -- no separate notched (BBB-/BB+) scale, so "below X" can be
# compared directly at breach-evaluation time.
RATING_TRIGGER_GRADES = [RatingGrade.BBB, RatingGrade.BB, RatingGrade.B]


def generate_csa_terms(
    seed: int = DEFAULT_SEED, as_of: date | None = None
) -> list[CSATermsDocument]:
    """Seeded, reproducible CSA terms per counterparty -- deliberately varying
    (not a fixed template) so retrieval tests are real, not a lookup table
    in disguise.
    """
    as_of = as_of or datetime.now(UTC).date()
    counterparties = generate_counterparties(seed)
    rng = random.Random(seed)

    documents: list[CSATermsDocument] = []
    for cp in counterparties:
        threshold = round(rng.uniform(50_000, 500_000) / 5_000) * 5_000
        mta = round(rng.uniform(10_000, 50_000) / 1_000) * 1_000
        eligible = sorted(rng.sample(list(COLLATERAL_HAIRCUTS), k=rng.randint(2, 3)))
        trigger_grade = rng.choice(RATING_TRIGGER_GRADES)

        documents.append(
            CSATermsDocument(
                counterparty_id=cp.id,
                counterparty_name=cp.name,
                threshold=float(threshold),
                mta=float(mta),
                currency="USD",
                eligible_collateral=eligible,
                haircuts={c: COLLATERAL_HAIRCUTS[c] for c in eligible},
                rating_triggers=[RatingTrigger(below_grade=trigger_grade, reduced_threshold=0.0)],
                effective_date=as_of,
            )
        )
    return documents


def render_csa_document(doc: CSATermsDocument) -> str:
    """Renders with clear section headers (Threshold, MTA, Eligible Collateral,
    Rating Triggers) so downstream chunking (MM-24) can keep each clause intact.
    """
    collateral_lines = "\n".join(
        f"- {c} (haircut: {doc.haircuts[c]:.0%})" for c in doc.eligible_collateral
    )
    trigger_lines = "\n".join(
        f"- If {doc.counterparty_name}'s credit rating falls below {t.below_grade}, the "
        f"Threshold is reduced to {doc.currency} {t.reduced_threshold:,.0f}."
        for t in doc.rating_triggers
    )

    return f"""# Credit Support Annex — {doc.counterparty_name} ({doc.counterparty_id})

Effective date: {doc.effective_date.isoformat()}

## Threshold

The Threshold applicable to {doc.counterparty_name} is {doc.currency} {doc.threshold:,.0f}.

## Minimum Transfer Amount

The Minimum Transfer Amount (MTA) applicable to {doc.counterparty_name} is \
{doc.currency} {doc.mta:,.0f}.

## Eligible Collateral

The following collateral types are eligible for {doc.counterparty_name}, with the \
haircuts shown:

{collateral_lines}

## Rating Triggers

{trigger_lines}
"""


def write_corpus(output_dir: Path = DEFAULT_OUTPUT_DIR, seed: int = DEFAULT_SEED) -> list[Path]:
    csa_dir = output_dir / "csa"
    csa_dir.mkdir(parents=True, exist_ok=True)

    paths: list[Path] = []
    for doc in generate_csa_terms(seed):
        path = csa_dir / f"{doc.counterparty_id}.md"
        path.write_text(render_csa_document(doc), encoding="utf-8")
        paths.append(path)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate MarginMaestro's CSA document corpus")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    paths = write_corpus(output_dir=args.output_dir, seed=args.seed)
    print(f"Wrote {len(paths)} CSA documents to {args.output_dir / 'csa'}")


if __name__ == "__main__":
    main()
