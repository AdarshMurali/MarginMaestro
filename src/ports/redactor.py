"""Masks personal and account data in text (MM-115, ADR-0014/0015) before it
reaches the model or the RAG index. Two implementations: Sensitive Data
Protection on GCP and a strict in-code fallback (post-trial, ADR-0017)."""

from typing import Protocol


class Redactor(Protocol):
    name: str

    def redact(self, text: str) -> str:
        """The same text with sensitive values replaced by `[INFO_TYPE]`
        markers. Must fail loud (raise) rather than return unmasked text when
        masking itself fails."""
        ...
