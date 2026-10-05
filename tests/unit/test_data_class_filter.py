"""MM-135: the LLM data-class filter -- confidential fields never reach a
model unmasked. Every rule is driven by docs/data_catalog.yaml."""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from adapters import factory
from adapters.guarded_llm import GuardedLLM
from adapters.incode_guardrail import InCodeGuardrail
from agents.reconciliation import _build_break_summary
from calc.trade_diff import BreakItem, BreakType
from config.settings import Settings
from governance.catalog import get_catalog
from governance.classification import (
    MASK,
    DataClassFilter,
    DbPseudonymSource,
    static_filter,
)
from persistence.db.models import Base, CounterpartyORM
from ports.guardrail import GuardrailBlocked, GuardrailUnavailable

CSA_CHUNK = (
    "# Credit Support Annex — Yang Partners (CP-3)\n"
    "The Threshold applicable to Yang Partners is USD 90,000.\n"
    "If Yang Partners's credit rating falls below B, the Threshold is reduced to USD 0."
)
BCRYPT = "$2b$12$" + "a" * 53


class _Names:
    def __init__(self, mapping: dict[str, str] | None = None) -> None:
        self.mapping = mapping if mapping is not None else {"Yang Partners": "CP-3"}
        self.calls = 0

    def pseudonyms(self, table: str, column: str, pseudonym: str) -> dict[str, str]:
        assert (table, column, pseudonym) == ("counterparties", "name", "id")
        self.calls += 1
        return self.mapping


def _filter(mapping: dict[str, str] | None = None) -> DataClassFilter:
    return DataClassFilter(get_catalog(), _Names(mapping))


# --- free text ------------------------------------------------------------------


def test_counterparty_legal_names_are_pseudonymized():
    out = _filter().redact(CSA_CHUNK)

    assert "Yang" not in out
    assert "Credit Support Annex — CP-3 (CP-3)" in out
    assert "If CP-3's credit rating" in out
    # CSA terms (internal) are untouched: the extraction still works.
    assert "USD 90,000" in out and "below B" in out


def test_longest_name_wins_and_matching_is_whole_word_and_case_insensitive():
    data_filter = _filter({"Acme": "CP-1", "Acme Capital": "CP-2"})

    assert data_filter.redact("ACME CAPITAL and Acme, not Acmeville") == (
        "CP-2 and CP-1, not Acmeville"
    )


def test_text_without_confidential_values_is_unchanged():
    text = "Policy: calls are due by the deadline. NVDA moved USD 18.00."
    assert _filter().redact(text) == text


def test_a_denied_value_blocks_the_prompt():
    with pytest.raises(GuardrailBlocked) as exc:
        _filter().redact(f"user analyst1 hash {BCRYPT}")

    assert exc.value.verdict.guardrail == "data_class"
    assert exc.value.verdict.reasons == ["confidential:users.password_hash"]


def test_filter_fails_closed_when_pseudonyms_cannot_be_loaded():
    source = MagicMock()
    source.pseudonyms.side_effect = RuntimeError("db down")

    with pytest.raises(GuardrailUnavailable):
        DataClassFilter(get_catalog(), source).redact(CSA_CHUNK)


# --- structured fields ----------------------------------------------------------


def test_mask_record_applies_each_columns_handling():
    data_filter = _filter()

    assert data_filter.mask_record(
        "positions", {"ticker": "NVDA", "quantity": 1500.0, "trade_date": "2026-01-02"}
    ) == {"ticker": "NVDA", "quantity": MASK, "trade_date": "2026-01-02"}
    assert data_filter.mask_record("counterparties", {"id": "CP-3", "name": "Yang Partners"}) == {
        "id": "CP-3",
        "name": "CP-3",
    }
    assert data_filter.mask_record("collateral_items", {"value_usd": 1.0})["value_usd"] == MASK
    assert data_filter.mask_record("users", {"password_hash": "x"})["password_hash"] == MASK
    assert data_filter.mask_record("counterparties", {"name": None}) == {"name": None}


def test_unclassified_fields_and_tables_are_refused():
    data_filter = _filter()

    with pytest.raises(ValueError, match="positions.notional is not classified"):
        data_filter.mask_record("positions", {"notional": 1.0})
    with pytest.raises(ValueError, match="not in the data catalog"):
        data_filter.mask_record("exposures", {"value": 1.0})


def test_reconciliation_prompt_never_carries_position_sizes():
    summary = _build_break_summary(
        [
            BreakItem(
                ticker="NVDA",
                break_type=BreakType.QUANTITY_MISMATCH,
                our_quantity=100.0,
                counterparty_quantity=80.0,
            ),
            BreakItem(
                ticker="AAPL",
                break_type=BreakType.MISSING_IN_COUNTERPARTY_VIEW,
                our_quantity=50.0,
                counterparty_quantity=None,
            ),
        ]
    )

    assert "100" not in summary and "80" not in summary and "50" not in summary
    assert f"NVDA: quantity_mismatch (ours={MASK}, counterparty={MASK})" in summary
    assert f"(ours={MASK}, counterparty=None)" in summary


def test_static_filter_masks_fields_without_a_database():
    data_filter = static_filter(get_catalog())
    assert data_filter.mask_record("positions", {"quantity": 3.0}) == {"quantity": MASK}
    assert data_filter.redact(CSA_CHUNK) == CSA_CHUNK  # no names known


# --- pseudonyms from the database ------------------------------------------------


def _db() -> sessionmaker:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory_ = sessionmaker(bind=engine)
    with factory_() as session:
        session.add_all(
            [
                CounterpartyORM(id="CP-3", name="Yang Partners", type="Hedge Fund", country="US"),
                CounterpartyORM(id="CP-4", name="", type="Bank", country="UK"),
            ]
        )
        session.commit()
    return factory_


def test_db_source_reads_names_and_caches_them_until_the_ttl():
    session_factory = _db()
    now = [0.0]
    source = DbPseudonymSource(session_factory, ttl_seconds=60, clock=lambda: now[0])

    assert source.pseudonyms("counterparties", "name", "id") == {"Yang Partners": "CP-3"}

    with session_factory() as session:
        session.add(CounterpartyORM(id="CP-9", name="New Fund", type="Bank", country="US"))
        session.commit()
    assert "New Fund" not in source.pseudonyms("counterparties", "name", "id")  # cached
    now[0] = 61.0
    assert source.pseudonyms("counterparties", "name", "id")["New Fund"] == "CP-9"


def test_end_to_end_filter_over_the_database():
    data_filter = DataClassFilter(get_catalog(), DbPseudonymSource(_db()))
    assert "Yang" not in data_filter.redact(CSA_CHUNK)


# --- wiring: every app LLM call ---------------------------------------------------


def test_guarded_llm_filters_before_masking_and_the_model():
    model, redactor = MagicMock(), MagicMock()
    redactor.name = "regex"
    redactor.redact.side_effect = lambda text: text
    model.complete.return_value = "ok"
    guarded = GuardedLLM(model, InCodeGuardrail(), redactor, data_filter=_filter())

    guarded.complete("system", CSA_CHUNK)

    sent = model.complete.call_args.args[1]
    assert "Yang" not in sent and "CP-3" in sent
    assert "Yang" not in redactor.redact.call_args.args[0]


def test_guarded_llm_blocks_a_denied_value_and_never_calls_the_model():
    model = MagicMock()
    guarded = GuardedLLM(model, InCodeGuardrail(), data_filter=_filter())

    with pytest.raises(GuardrailBlocked):
        guarded.complete("system", f"hash {BCRYPT}")
    model.complete.assert_not_called()


def test_guarded_llm_fails_closed_when_the_filter_is_unavailable():
    model, source = MagicMock(), MagicMock()
    source.pseudonyms.side_effect = RuntimeError("db down")
    guarded = GuardedLLM(
        model, InCodeGuardrail(), data_filter=DataClassFilter(get_catalog(), source)
    )

    with pytest.raises(GuardrailUnavailable):
        guarded.parse("system", CSA_CHUNK, MagicMock())
    model.parse.assert_not_called()


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, openai_api_key="sk-test", **overrides)


def test_factory_default_is_no_filter_and_catalog_turns_it_on():
    assert factory.get_data_class_filter(_settings()) is None
    assert factory.get_llm(_settings())._data_filter is None

    data_filter = factory.get_data_class_filter(
        _settings(llm_data_class_filter="catalog"), session_factory=_db()
    )
    assert isinstance(data_filter, DataClassFilter)
    assert "Yang" not in data_filter.redact(CSA_CHUNK)

    with pytest.raises(ValueError, match="LLM_DATA_CLASS_FILTER"):
        factory.get_data_class_filter(_settings(llm_data_class_filter="sometimes"))


def test_without_a_session_factory_the_filter_is_built_once_per_process(monkeypatch):
    """get_llm() runs per agent call; one engine and one pseudonym cache serve all."""
    monkeypatch.setattr(factory, "_PROCESS_DATA_FILTER", {})
    session_factory = _db()
    with patch("persistence.db.engine.get_session_factory", return_value=session_factory) as get:
        first = factory.get_data_class_filter(_settings(llm_data_class_filter="catalog"))
        second = factory.get_llm(_settings(llm_data_class_filter="catalog"))._data_filter

    assert first is second
    get.assert_called_once()


def test_seeded_counterparty_names_are_all_pseudonymized():
    """Every name the generators seed is covered (the real demo book)."""
    from persistence.generators.counterparties import generate_counterparties

    names = {cp.name: cp.id for cp in generate_counterparties(42)}
    text = " / ".join(names)
    out = _filter(names).redact(text)
    assert all(name not in out for name in names)
