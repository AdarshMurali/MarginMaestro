from unittest.mock import patch

from persistence.models import RATING_ORDER
from rag.csa_corpus import (
    COLLATERAL_HAIRCUTS,
    RATING_TRIGGER_GRADES,
    generate_csa_terms,
    main,
    render_csa_document,
    write_corpus,
)


class TestGenerateCsaTerms:
    def test_generates_one_document_per_counterparty(self) -> None:
        docs = generate_csa_terms(seed=42)

        assert len(docs) == 8
        assert {d.counterparty_id for d in docs} == {f"CP-{i}" for i in range(1, 9)}

    def test_is_deterministic_for_the_same_seed(self) -> None:
        first = generate_csa_terms(seed=42)
        second = generate_csa_terms(seed=42)

        assert [d.model_dump() for d in first] == [d.model_dump() for d in second]

    def test_different_seeds_produce_different_terms(self) -> None:
        first = generate_csa_terms(seed=42)
        other = generate_csa_terms(seed=7)

        assert [d.threshold for d in first] != [d.threshold for d in other]

    def test_terms_vary_across_counterparties(self) -> None:
        docs = generate_csa_terms(seed=42)

        # If every counterparty got identical terms, this wouldn't be a real
        # retrieval test -- it'd be a lookup table in disguise.
        assert len({d.threshold for d in docs}) > 1
        assert len({d.mta for d in docs}) > 1

    def test_thresholds_and_mtas_are_within_realistic_ranges(self) -> None:
        docs = generate_csa_terms(seed=42)

        for doc in docs:
            assert 50_000 <= doc.threshold <= 500_000
            assert 10_000 <= doc.mta <= 50_000

    def test_haircuts_match_the_eligible_collateral_list(self) -> None:
        docs = generate_csa_terms(seed=42)

        for doc in docs:
            assert set(doc.haircuts) == set(doc.eligible_collateral)
            for collateral_type in doc.eligible_collateral:
                assert doc.haircuts[collateral_type] == COLLATERAL_HAIRCUTS[collateral_type]

    def test_rating_triggers_use_real_rating_grades_with_a_concrete_threshold(self) -> None:
        docs = generate_csa_terms(seed=42)

        for doc in docs:
            assert len(doc.rating_triggers) == 1
            trigger = doc.rating_triggers[0]
            assert trigger.below_grade in RATING_TRIGGER_GRADES
            assert trigger.below_grade in RATING_ORDER
            assert trigger.reduced_threshold == 0.0


class TestRenderCsaDocument:
    def test_rendered_document_contains_all_key_terms(self) -> None:
        doc = generate_csa_terms(seed=42)[0]

        rendered = render_csa_document(doc)

        assert doc.counterparty_name in rendered
        assert doc.counterparty_id in rendered
        assert f"{doc.threshold:,.0f}" in rendered
        assert f"{doc.mta:,.0f}" in rendered
        for collateral_type in doc.eligible_collateral:
            assert collateral_type in rendered
        assert "## Threshold" in rendered
        assert "## Minimum Transfer Amount" in rendered
        assert "## Eligible Collateral" in rendered
        assert "## Rating Triggers" in rendered
        trigger = doc.rating_triggers[0]
        assert trigger.below_grade in rendered
        assert f"{trigger.reduced_threshold:,.0f}" in rendered


class TestWriteCorpus:
    def test_writes_one_file_per_counterparty_matching_rendered_content(self, tmp_path) -> None:
        paths = write_corpus(output_dir=tmp_path, seed=42)

        assert len(paths) == 8
        assert {p.name for p in paths} == {f"CP-{i}.md" for i in range(1, 9)}

        docs = {d.counterparty_id: d for d in generate_csa_terms(seed=42)}
        for path in paths:
            counterparty_id = path.stem
            assert path.parent == tmp_path / "csa"
            assert path.read_text(encoding="utf-8") == render_csa_document(docs[counterparty_id])


class TestMain:
    def test_parses_args_and_writes_corpus(self, tmp_path, capsys) -> None:
        with patch("sys.argv", ["csa_corpus", "--seed", "7", "--output-dir", str(tmp_path)]):
            main()

        assert (tmp_path / "csa").exists()
        assert len(list((tmp_path / "csa").glob("*.md"))) == 8
        assert "Wrote 8 CSA documents" in capsys.readouterr().out
