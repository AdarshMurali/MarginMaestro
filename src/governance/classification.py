"""The LLM data-class filter (MM-135, ADR-0015): confidential data never
reaches a model unmasked. Driven entirely by the data catalog
(`docs/data_catalog.yaml`), so a column's class and its handling live in one
place.

- Free text (a prompt, a retrieved chunk) -- `DataClassFilter.redact`:
  * `deny` columns with a `pattern` (e.g. a bcrypt password hash): the text is
    blocked (`GuardrailBlocked`), never trimmed and sent;
  * `pseudonymize` columns (a counterparty's legal name): every known value is
    replaced by its pseudonym ("Yang Partners" -> "CP-3"). The values come from
    the database, so a new counterparty is covered without a code change.
- Structured fields -- `DataClassFilter.mask_record(table, record)`: every
  field is looked up in the catalog. `mask`/`deny` fields become
  `[CONFIDENTIAL]`, `pseudonymize` fields their pseudonym, and a field the
  catalog doesn't know raises: unclassified data isn't sent anywhere.

Fail loud: if the pseudonyms can't be loaded the filter raises
`GuardrailUnavailable`, and the call is held like any other guardrail outage.

The one deliberate exception (the desk assistant quoting call amounts to the
analyst who owns the book) is listed under `llm_exceptions` in the catalog.
"""

import re
import time
from collections.abc import Callable, Mapping
from typing import Any, Protocol

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from governance.catalog import DataCatalog
from ports.guardrail import GuardrailBlocked, GuardrailUnavailable, Verdict

MASK = "[CONFIDENTIAL]"
FILTER_NAME = "data_class"
logger = structlog.get_logger(__name__)


class PseudonymSource(Protocol):
    def pseudonyms(self, table: str, column: str, pseudonym: str) -> dict[str, str]:
        """{value: pseudonym} for every row of `table`."""
        ...


class DbPseudonymSource:
    """Reads value -> pseudonym pairs from the application database (an
    internal, firm-wide session) and caches them for `ttl_seconds`."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        ttl_seconds: float = 300.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._session_factory = session_factory
        self._ttl = ttl_seconds
        self._clock = clock
        self._cache: dict[tuple[str, str, str], tuple[float, dict[str, str]]] = {}

    def pseudonyms(self, table: str, column: str, pseudonym: str) -> dict[str, str]:
        key = (table, column, pseudonym)
        cached = self._cache.get(key)
        if cached is not None and self._clock() - cached[0] < self._ttl:
            return cached[1]
        from persistence.db.models import Base

        model_table = Base.metadata.tables[table]
        with self._session_factory() as session:
            rows = session.execute(select(model_table.c[column], model_table.c[pseudonym])).all()
        mapping = {str(value): str(alias) for value, alias in rows if value}
        self._cache[key] = (self._clock(), mapping)
        return mapping


class DataClassFilter:
    name = FILTER_NAME

    def __init__(self, catalog: DataCatalog, source: PseudonymSource) -> None:
        self._catalog = catalog
        self._source = source
        self._deny_patterns = [
            (f"{table}.{column}", re.compile(entry.pattern))
            for table, column, entry in catalog.columns_with("deny")
            if entry.pattern
        ]
        self._pseudonymized = [
            (table, column, entry.pseudonym)
            for table, column, entry in catalog.columns_with("pseudonymize")
            if entry.pseudonym
        ]

    def _mappings(self) -> list[dict[str, str]]:
        try:
            return [
                self._source.pseudonyms(table, column, pseudonym)
                for table, column, pseudonym in self._pseudonymized
            ]
        except Exception as exc:  # fail closed: no pseudonyms, no prompt
            logger.error("data_class_filter_unavailable", error=str(exc))
            raise GuardrailUnavailable("the data-class filter could not load pseudonyms") from exc

    def _check_denied(self, text: str) -> None:
        reasons = [
            f"confidential:{ref}" for ref, pattern in self._deny_patterns if pattern.search(text)
        ]
        if reasons:
            raise GuardrailBlocked(
                "prompt", Verdict(allowed=False, guardrail=self.name, reasons=reasons)
            )

    def redact(self, text: str) -> str:
        """The text with every confidential value it may carry pseudonymized;
        blocked outright if it carries a `deny` value."""
        self._check_denied(text)
        replaced = 0
        for mapping in self._mappings():
            # Longest first, so "Yang Partners Ltd" wins over "Yang Partners".
            for value in sorted(mapping, key=len, reverse=True):
                pattern = re.compile(rf"(?<!\w){re.escape(value)}(?!\w)", re.IGNORECASE)
                text, count = pattern.subn(mapping[value], text)
                replaced += count
        if replaced:
            logger.info("prompt_pseudonymized", filter=self.name, replacements=replaced)
        return text

    def mask_record(self, table: str, record: Mapping[str, Any]) -> dict[str, Any]:
        """A copy of `record` (fields of catalog table `table`) that is safe to
        put in a prompt. Unknown tables and fields raise."""
        if table not in self._catalog.tables:
            raise ValueError(f"table {table!r} is not in the data catalog")
        columns = self._catalog.tables[table].columns
        safe: dict[str, Any] = {}
        for field, value in record.items():
            if field not in columns:
                raise ValueError(f"{table}.{field} is not classified in the data catalog")
            entry = columns[field]
            if entry.llm in ("mask", "deny"):
                safe[field] = MASK
            elif entry.llm == "pseudonymize":
                safe[field] = self.redact(str(value)) if value is not None else None
            else:
                safe[field] = value
        return safe


def static_filter(catalog: DataCatalog) -> DataClassFilter:
    """A filter for structured-field masking only (no database): pseudonymizing
    free text with it finds no values, so use `DataClassFilter` with a
    `DbPseudonymSource` for prompts."""

    class _NoPseudonyms:
        def pseudonyms(self, table: str, column: str, pseudonym: str) -> dict[str, str]:
            return {}

    return DataClassFilter(catalog, _NoPseudonyms())
