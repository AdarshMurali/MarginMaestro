"""MM-115: masking personal/account data before the model and the RAG index."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from adapters import factory
from adapters.guarded_llm import GuardedLLM
from adapters.incode_guardrail import NoGuardrail
from adapters.redactors import INFO_TYPES, NoRedactor, RegexRedactor, SdpRedactor
from config.settings import Settings

CORPUS = Path(__file__).resolve().parents[2] / "data" / "documents"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("mail jane.doe@hallfinancial.com today", "mail [EMAIL_ADDRESS] today"),
        ("call +44 20 7946 0958 now", "call [PHONE_NUMBER] now"),
        ("IBAN GB82 WEST 1234 5698 7654 32", "IBAN [IBAN_CODE]"),
        ("IBAN GB82WEST12345698765432", "IBAN [IBAN_CODE]"),
        ("card 4111 1111 1111 1111", "card [CREDIT_CARD_NUMBER]"),
        ("card 4111-1111-1111-1111", "card [CREDIT_CARD_NUMBER]"),
    ],
)
def test_regex_masks_valid_identifiers(text, expected):
    assert RegexRedactor().redact(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Threshold USD 240,000 effective 2026-08-16.",
        "Call amount 139,525.76 due 2026-10-01 17:00.",
        "Reference 1234 5678 9012 3456 (fails Luhn).",
        "IBAN-shaped GB00 WEST 1234 5698 7654 32 (fails mod-97).",
        "Local number 020 7946 0958 without a + prefix.",
    ],
)
def test_regex_leaves_amounts_dates_and_invalid_numbers_alone(text):
    assert RegexRedactor().redact(text) == text


@pytest.mark.parametrize("path", sorted(CORPUS.rglob("*.md")), ids=lambda p: p.name)
def test_regex_never_changes_the_real_corpus(path):
    text = path.read_text(encoding="utf-8")
    assert RegexRedactor().redact(text) == text


def test_no_redactor_is_identity():
    assert NoRedactor().redact("jane@x.com") == "jane@x.com"


# --- Sensitive Data Protection ---------------------------------------------------


def _sdp(value="masked"):
    client = MagicMock()
    client.deidentify_content.return_value = SimpleNamespace(item=SimpleNamespace(value=value))
    return SdpRedactor("proj-x", "us-central1", client), client


def test_sdp_request_is_regional_likely_and_replaces_with_info_type():
    redactor, client = _sdp("mail [EMAIL_ADDRESS]")

    assert redactor.redact("mail jane@x.com") == "mail [EMAIL_ADDRESS]"

    request = client.deidentify_content.call_args.kwargs["request"]
    assert request["parent"] == "projects/proj-x/locations/us-central1"
    assert request["item"] == {"value": "mail jane@x.com"}
    assert request["inspect_config"]["min_likelihood"] == "LIKELY"
    assert [t["name"] for t in request["inspect_config"]["info_types"]] == INFO_TYPES
    transformation = request["deidentify_config"]["info_type_transformations"]["transformations"][0]
    assert "replace_with_info_type_config" in transformation["primitive_transformation"]


def test_sdp_never_masks_person_names():
    # Counterparty names ("Rodriguez Partners") must reach the CSA extraction.
    assert "PERSON_NAME" not in INFO_TYPES


def test_sdp_skips_blank_text_without_a_call():
    redactor, client = _sdp()

    assert redactor.redact("   ") == "   "
    client.deidentify_content.assert_not_called()


def test_sdp_failure_propagates_rather_than_returning_unmasked_text():
    redactor, client = _sdp()
    client.deidentify_content.side_effect = RuntimeError("503")

    with pytest.raises(RuntimeError):
        redactor.redact("mail jane@x.com")


# --- wiring ------------------------------------------------------------------------


def test_guarded_llm_masks_before_screening_and_before_the_model():
    model = MagicMock()
    model.complete.return_value = "ok"
    guardrail = MagicMock(wraps=NoGuardrail())
    guardrail.name = "none"

    GuardedLLM(model, guardrail, RegexRedactor()).complete("s", "reply from jane@x.com")

    assert guardrail.screen.call_args_list[0].args == ("reply from [EMAIL_ADDRESS]", "prompt")
    assert model.complete.call_args.args == ("s", "reply from [EMAIL_ADDRESS]")


def test_masking_failure_stops_the_call():
    broken = MagicMock()
    broken.name = "sdp"
    broken.redact.side_effect = RuntimeError("down")
    model = MagicMock()

    with pytest.raises(RuntimeError):
        GuardedLLM(model, NoGuardrail(), broken).complete("s", "u")
    model.complete.assert_not_called()


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, openai_api_key="sk-test", **overrides)


def test_factory_default_is_the_regex_redactor_on_every_llm():
    llm = factory.get_llm(_settings())

    assert isinstance(llm._redactor, RegexRedactor)


def test_factory_sdp_redactor():
    with patch("adapters.redactors.dlp_client", return_value=MagicMock()):
        redactor = factory.get_redactor(_settings(redactor_provider="sdp", gcp_project_id="proj-x"))

    assert redactor.name == "sdp+regex"
    sdp = redactor._redactors[0]
    assert isinstance(sdp, SdpRedactor)
    assert sdp._parent == "projects/proj-x/locations/us-central1"


def test_factory_sdp_requires_a_project():
    with pytest.raises(ValueError, match="GCP_PROJECT_ID"):
        factory.get_redactor(_settings(redactor_provider="sdp"))


def test_unknown_redactor_fails_loud():
    with pytest.raises(ValueError, match="REDACTOR_PROVIDER"):
        factory.get_redactor(_settings(redactor_provider="sharpie"))


def test_ingestion_masks_chunks_before_embedding_and_storing():
    from rag.ingest import run_ingestion

    embedder = MagicMock()
    embedder.embed.side_effect = lambda texts: [[0.0]] * len(texts)
    store = MagicMock()
    docs = [("disputes/note.md", "# Note\n\nClient wrote from jane@x.com about the stale price.")]

    run_ingestion(
        settings=_settings(),
        documents=docs,
        embedder=embedder,
        vector_store=store,
        redactor=RegexRedactor(),
    )

    stored = store.upsert.call_args.kwargs["documents"]
    assert all("jane@x.com" not in text for text in stored)
    assert any("[EMAIL_ADDRESS]" in text for text in stored)
    assert embedder.embed.call_args.args[0] == stored


def test_chain_applies_each_redactor_in_order():
    from adapters.redactors import ChainedRedactor

    sdp, _ = _sdp("mail [EMAIL_ADDRESS], call +44 20 7946 0958")
    chain = ChainedRedactor([sdp, RegexRedactor()])

    assert chain.redact("mail jane@x.com, call +44 20 7946 0958") == (
        "mail [EMAIL_ADDRESS], call [PHONE_NUMBER]"
    )


def test_chain_needs_at_least_one():
    from adapters.redactors import ChainedRedactor

    with pytest.raises(ValueError):
        ChainedRedactor([])
