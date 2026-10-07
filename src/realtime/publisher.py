"""MM-146 (ADR-0021): one small status document per margin call in Firestore,
rewritten whenever the call's lifecycle moves (raised, re-evaluated,
approved, manager-approved, notified, acknowledged / SLA met, escalated,
rejected). Subscribed browsers get the change pushed to them instantly, while
the API and Cloud SQL stay asleep.

Rules:
- Postgres (the LangGraph checkpoints) stays the source of truth. The doc is a
  projection of the same MarginCallSummary the /margin-calls feed returns:
  every field is copied from it, nothing is computed here (ADR-0005).
- Best effort: a failed write logs a warning and never fails the call.
- Idempotent: the doc id is the run's thread_id and each write replaces the
  whole doc, so replaying a transition rewrites the same doc. An unchanged
  status is not rewritten at all (no extra Firestore writes or pushes).
- No names, notice text or rationale -- the doc carries ids, status and the
  call figure only; the browser refetches the full row through the API, which
  applies the caller's row-level security.
"""

import threading
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any, Protocol

import structlog
from pydantic import BaseModel

from adapters.selection import choose
from config.settings import Settings, get_settings
from warehouse.schemas import Book

logger = structlog.get_logger()

# Bounds the in-process "last published" cache (one entry per thread_id).
_DEDUPE_LIMIT = 2_000


class CallStatusDoc(BaseModel):
    """The Firestore document for one margin call (`<collection>/<doc_id>`)."""

    thread_id: str
    counterparty_id: str
    status: str
    call_amount: float | None
    currency: str
    sla_deadline: datetime | None
    updated_at: datetime
    # Orchestrator runs are always on the live book (the simulated book exists
    # only in the warehouse, MM-140).
    book: str = Book.LIVE.value


def doc_id(thread_id: str) -> str:
    """Firestore ids can't contain '/'; thread ids are `<event_id>:<cp>`."""
    return thread_id.replace("/", "_")


def status_doc(
    thread_id: str, values: dict, settings: Settings, now: datetime | None = None
) -> CallStatusDoc:
    """Copies the feed's own summary of this run -- one place derives status."""
    from api.margin_calls import summarize_run

    summary = summarize_run(thread_id, values, settings)
    return CallStatusDoc(
        thread_id=thread_id,
        counterparty_id=summary.counterparty_id,
        status=summary.status.value,
        call_amount=summary.call_amount,
        currency=summary.currency,
        sla_deadline=summary.sla_deadline,
        updated_at=now or datetime.now(UTC),
    )


class StatusPublisher(Protocol):
    enabled: bool

    def publish(self, thread_id: str, values: dict) -> None: ...


class NoStatusPublisher:
    """REALTIME=none (the default): nothing is published; the frontend polls."""

    enabled = False

    def publish(self, thread_id: str, values: dict) -> None:
        return None


class FirestoreStatusPublisher:
    """Writes CallStatusDoc to Firestore. `client` is a google.cloud.firestore
    Client (or anything with the same collection().document().set() shape)."""

    enabled = True

    def __init__(self, client: Any, collection: str, settings: Settings) -> None:
        self._client = client
        self._collection = collection
        self._settings = settings
        self._last: dict[str, tuple] = {}
        self._lock = threading.Lock()

    def publish(self, thread_id: str, values: dict) -> None:
        try:
            doc = status_doc(thread_id, values, self._settings)
            fingerprint = (doc.status, doc.call_amount, doc.currency, doc.sla_deadline)
            with self._lock:
                if self._last.get(thread_id) == fingerprint:
                    return
            self._client.collection(self._collection).document(doc_id(thread_id)).set(
                doc.model_dump()
            )
            with self._lock:
                if len(self._last) >= _DEDUPE_LIMIT:
                    self._last.clear()
                self._last[thread_id] = fingerprint
            logger.info("realtime_status_published", thread_id=thread_id, status=doc.status)
        except Exception as exc:  # noqa: BLE001 -- best effort: never fails the call
            logger.warning("realtime_publish_failed", thread_id=thread_id, error=type(exc).__name__)


def build_status_publisher(settings: Settings, client: Any = None) -> StatusPublisher:
    choice = choose("REALTIME", settings.realtime, ("none", "firestore"))
    if choice == "none":
        return NoStatusPublisher()
    if client is None:
        if not settings.gcp_project_id:
            raise ValueError("REALTIME=firestore requires GCP_PROJECT_ID")
        from google.cloud import firestore

        client = firestore.Client(
            project=settings.gcp_project_id, database=settings.firestore_database
        )
    return FirestoreStatusPublisher(client, settings.realtime_collection, settings)


@lru_cache
def get_status_publisher() -> StatusPublisher:
    """One publisher (one Firestore client) per process."""
    return build_status_publisher(get_settings())
