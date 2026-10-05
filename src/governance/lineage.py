"""Lineage per margin call (MM-136, ADR-0015): OpenLineage run events sent to
Dataplex's Data Lineage API (`processOpenLineageRunEvent`).

One margin call = one OpenLineage run of the job
`marginmaestro/margin_call_lifecycle` (a Data Lineage *process*); its run id is
derived from the call's thread id, so every event of a call lands on the same
run, and a replayed or re-sent event is harmless. Each lifecycle milestone is
one event, and its inputs -> outputs become lineage links:

  call raised   price event + positions, prices, VIX, collateral, ratings,
                counterparty tier + the cited CSA files  -> margin call
  approval      margin call                              -> approval
  notification  approval                                 -> notification
  resolution    notification -> SLA met | escalation (ServiceNow incident)

Dataset names match the Dataplex catalog entries (MM-135):
`custom:marginmaestro.cloudsql.<table>` for tables, `gs://<bucket>/<object>`
for documents, `custom:marginmaestro.<kind>.<id>` for a call's own records.
No amounts or names go into lineage metadata -- only ids (the amounts are
confidential in the data catalog).

Best effort by design: a failure is logged at warning and never blocks or
fails the margin call (`LINEAGE_EXPORTER=none` is the default; AWS/local
unchanged).
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal, Protocol
from uuid import NAMESPACE_URL, uuid5

import structlog

from adapters.selection import choose
from config.settings import Settings

if TYPE_CHECKING:
    from agents.orchestrator import MarginCallState

logger = structlog.get_logger(__name__)

PRODUCER = "https://github.com/AdarshMurali/MarginMaestro"
RUN_EVENT_SCHEMA = "https://openlineage.io/spec/2-0-2/OpenLineage.json#/$defs/RunEvent"
FACET_SCHEMA = "https://openlineage.io/spec/2-0-2/OpenLineage.json#/$defs/RunFacet"
JOB_NAMESPACE = "marginmaestro"
JOB_NAME = "margin_call_lifecycle"
LINEAGE_API = "https://datalineage.googleapis.com/v1"
EventType = Literal["START", "RUNNING", "COMPLETE", "FAIL"]

# What compute_exposure / evaluate_breach read (agents/orchestrator.py).
CALC_INPUT_TABLES = (
    "positions",
    "portfolios",
    "latest_prices",
    "price_history",
    "reference_rates",
    "collateral_items",
    "ratings",
    "counterparties",
)


class LineageExporter(Protocol):
    name: str

    def emit(self, event: dict[str, Any]) -> None:
        """Send one OpenLineage run event. May raise; callers are best effort."""
        ...


class NoLineageExporter:
    name = "none"

    def emit(self, event: dict[str, Any]) -> None:
        return None


class DataLineageExporter:
    """POST projects/<p>/locations/<l>:processOpenLineageRunEvent, as the
    runtime service account (roles/datalineage.producer)."""

    name = "datalineage"

    def __init__(self, project_id: str, location: str, session: Any | None = None) -> None:
        self._url = (
            f"{LINEAGE_API}/projects/{project_id}/locations/{location}:processOpenLineageRunEvent"
        )
        self._session = session

    def _authorized_session(self) -> Any:
        if self._session is None:
            # Imported lazily: only needed when LINEAGE_EXPORTER=datalineage.
            from google.auth import default as google_default_credentials
            from google.auth.transport.requests import AuthorizedSession

            credentials, _ = google_default_credentials(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            self._session = AuthorizedSession(credentials)
        return self._session

    def emit(self, event: dict[str, Any]) -> None:
        response = self._authorized_session().post(self._url, json=event, timeout=10)
        response.raise_for_status()


def get_lineage_exporter(settings: Settings) -> LineageExporter:
    choice = choose("LINEAGE_EXPORTER", settings.lineage_exporter, ("none", "datalineage"))
    if choice == "none":
        return NoLineageExporter()
    if not settings.gcp_project_id:
        raise ValueError("LINEAGE_EXPORTER=datalineage requires GCP_PROJECT_ID")
    return DataLineageExporter(settings.gcp_project_id, settings.lineage_location)


def run_id_for(thread_id: str) -> str:
    """Stable per call: every milestone of one call is the same lineage run."""
    return str(uuid5(NAMESPACE_URL, f"marginmaestro:margin-call:{thread_id}"))


def table_dataset(table: str) -> dict[str, str]:
    return {"namespace": "custom", "name": f"marginmaestro.cloudsql.{table}"}


def record_dataset(kind: str, record_id: str) -> dict[str, str]:
    return {"namespace": "custom", "name": f"marginmaestro.{kind}.{record_id}"}


def document_dataset(bucket: str | None, source_file: str) -> dict[str, str]:
    if bucket:
        return {"namespace": f"gs://{bucket}", "name": source_file}
    return {"namespace": "custom", "name": f"marginmaestro.documents.{source_file}"}


class MarginCallLineage:
    """Builds and emits the lineage events of one margin call's milestones."""

    def __init__(self, exporter: LineageExporter, documents_bucket: str | None = None) -> None:
        self._exporter = exporter
        self._bucket = documents_bucket

    @property
    def enabled(self) -> bool:
        return self._exporter.name != "none"

    # --- milestones ---------------------------------------------------------------

    def call_raised(self, state: "MarginCallState", thread_id: str) -> None:
        def build() -> dict[str, Any]:
            events = {state.impact.event_id, state.current_trigger.event_id}
            citations = [
                {
                    "source_file": c.source_file,
                    "section": c.section,
                    "chunk_id": f"{c.source_file}#{c.section}",
                }
                for c in state.csa_citations
            ]
            files = sorted({c.source_file for c in state.csa_citations})
            return self._event(
                thread_id,
                "START",
                inputs=[record_dataset("price_event", e) for e in sorted(events)]
                + [table_dataset(t) for t in CALC_INPUT_TABLES]
                + [document_dataset(self._bucket, f) for f in files],
                outputs=[record_dataset("margin_call", thread_id)],
                facets={
                    "counterparty_id": state.counterparty_id,
                    "correlation_id": state.correlation_id,
                    "trigger_event_id": state.current_trigger.event_id,
                    "event_type": state.current_trigger.event_type.value,
                    "csa_citations": citations,
                    "updated_by": state.updated_by,
                },
                milestone="call_raised",
            )

        self._emit(build, thread_id, "call_raised")

    def approval(
        self,
        state: "MarginCallState",
        thread_id: str,
        decision: str,
        approver: str | None,
        second_signature: bool = False,
    ) -> None:
        final = decision not in ("approved", "adjusted")

        def build() -> dict[str, Any]:
            return self._event(
                thread_id,
                "COMPLETE" if final else "RUNNING",
                inputs=[record_dataset("margin_call", thread_id)],
                outputs=[record_dataset("approval", thread_id)],
                facets={
                    "counterparty_id": state.counterparty_id,
                    "decision": decision,
                    "approver": approver,
                    "second_signature": second_signature,
                },
                milestone="manager_approval" if second_signature else "approval",
            )

        self._emit(build, thread_id, "approval")

    def notified(
        self,
        state: "MarginCallState",
        thread_id: str,
        channel: str,
        message_id: str | None,
        delivery_status: str,
    ) -> None:
        def build() -> dict[str, Any]:
            return self._event(
                thread_id,
                "RUNNING",
                inputs=[record_dataset("approval", thread_id)],
                outputs=[record_dataset("notification", thread_id)],
                facets={
                    "counterparty_id": state.counterparty_id,
                    "channel": channel,
                    "message_id": message_id,
                    "delivery_status": delivery_status,
                },
                milestone="notification",
            )

        self._emit(build, thread_id, "notification")

    def resolved(
        self,
        state: "MarginCallState",
        thread_id: str,
        outcome: Literal["sla_met", "escalated"],
        incident_number: str | None = None,
    ) -> None:
        def build() -> dict[str, Any]:
            output = "escalation" if outcome == "escalated" else "resolution"
            return self._event(
                thread_id,
                "COMPLETE",
                inputs=[record_dataset("notification", thread_id)],
                outputs=[record_dataset(output, thread_id)],
                facets={
                    "counterparty_id": state.counterparty_id,
                    "outcome": outcome,
                    "incident_number": incident_number,
                    "delivery_failure": state.delivery_failure,
                },
                milestone=outcome,
            )

        self._emit(build, thread_id, outcome)

    # --- plumbing ---------------------------------------------------------------

    def _event(
        self,
        thread_id: str,
        event_type: EventType,
        inputs: list[dict[str, str]],
        outputs: list[dict[str, str]],
        facets: dict[str, Any],
        milestone: str,
    ) -> dict[str, Any]:
        return {
            "eventType": event_type,
            "eventTime": datetime.now(UTC).isoformat(),
            "producer": PRODUCER,
            "schemaURL": RUN_EVENT_SCHEMA,
            "run": {
                "runId": run_id_for(thread_id),
                "facets": {
                    "marginmaestro_margin_call": {
                        "_producer": PRODUCER,
                        "_schemaURL": FACET_SCHEMA,
                        "thread_id": thread_id,
                        "milestone": milestone,
                        **facets,
                    }
                },
            },
            "job": {"namespace": JOB_NAMESPACE, "name": JOB_NAME},
            "inputs": inputs,
            "outputs": outputs,
        }

    def _emit(self, build: Callable[[], dict[str, Any]], thread_id: str, milestone: str) -> None:
        """Best effort: lineage never blocks or fails a margin call."""
        if not self.enabled:
            return
        try:
            self._exporter.emit(build())
        except Exception as exc:  # noqa: BLE001 -- see docstring
            logger.warning(
                "lineage_export_failed",
                exporter=self._exporter.name,
                thread_id=thread_id,
                milestone=milestone,
                error=str(exc),
            )
        else:
            logger.info("lineage_exported", thread_id=thread_id, milestone=milestone)


def get_margin_call_lineage(settings: Settings) -> MarginCallLineage:
    bucket = settings.gcs_documents_bucket if settings.document_store == "gcs" else None
    return MarginCallLineage(get_lineage_exporter(settings), bucket)
