"""SLA & Escalation (MM-43, docs/AGENTS.md "SLA & Escalation"): on an SLA
breach, retrieves the firm's escalation-procedures document (RAG) and opens
a ServiceNow incident with full run context -- ServiceNow, not Jira, for
this escalation path only (docs/adr/0007). The escalation procedure text is
retrieved, not LLM-summarized: AGENTS.md's Type line for this responsibility
is "code + RAG for procedure", not "llm" -- no LLM call in this module."""

from datetime import datetime

import httpx
from pydantic import BaseModel

from config.settings import Settings, get_settings
from rag.retriever import retrieve

HIGH_URGENCY_THRESHOLD_MULTIPLE = 5.0
DEFAULT_ESCALATION_QUERY = "How and when should a non-responsive margin call be escalated?"


class EscalationUnavailableError(Exception):
    """Raised when no escalation-procedures document chunks can be retrieved."""


class ServiceNowError(Exception):
    """Raised when ServiceNow isn't configured, or incident creation fails."""


class IncidentResult(BaseModel):
    incident_number: str
    sys_id: str
    urgency: str


def retrieve_escalation_procedure(
    query: str | None = None, top_k: int = 5, settings: Settings | None = None
) -> str:
    chunks = retrieve(
        query or DEFAULT_ESCALATION_QUERY, doc_type="escalation", top_k=top_k, settings=settings
    )
    if not chunks:
        raise EscalationUnavailableError("No escalation-procedures document chunks found")
    return "\n\n".join(f"[{chunk.section}]\n{chunk.text}" for chunk in chunks)


def open_servicenow_incident(
    correlation_id: str,
    counterparty_id: str,
    call_amount: float,
    currency: str,
    threshold: float,
    notification_sent_at: datetime,
    deadline: datetime,
    procedure_excerpt: str,
    settings: Settings | None = None,
    http_client: httpx.Client | None = None,
) -> IncidentResult:
    settings = settings or get_settings()
    if not (
        settings.servicenow_instance_url
        and settings.servicenow_username
        and settings.servicenow_password
    ):
        raise ServiceNowError("SERVICENOW_INSTANCE_URL/USERNAME/PASSWORD are not configured")

    # High urgency past 5x threshold (or any positive call against a
    # zero/undefined threshold -- see escalation_procedures.md's Incident
    # Priority section), otherwise moderate.
    urgency = (
        "1" if threshold <= 0 or call_amount / threshold > HIGH_URGENCY_THRESHOLD_MULTIPLE else "2"
    )
    description = (
        f"Margin call SLA breach for counterparty {counterparty_id}.\n"
        f"Call amount: {call_amount:,.2f} {currency}\n"
        f"Notified: {notification_sent_at.isoformat()}\n"
        f"SLA deadline missed: {deadline.isoformat()}\n"
        f"Correlation id: {correlation_id}\n\n"
        f"Escalation procedure:\n{procedure_excerpt}"
    )

    # httpx's default 5s timeout is too short for a real ServiceNow PDI --
    # confirmed by a live call timing out at the default before succeeding
    # at 30s (the instance itself wasn't hibernating; ServiceNow PDIs are
    # just genuinely slower than most REST APIs).
    client = http_client or httpx.Client(
        base_url=settings.servicenow_instance_url,
        auth=(settings.servicenow_username, settings.servicenow_password),
        timeout=30.0,
    )
    try:
        response = client.post(
            "/api/now/table/incident",
            json={
                "short_description": f"Margin call SLA breach -- {counterparty_id}",
                "description": description,
                "urgency": urgency,
            },
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ServiceNowError(f"ServiceNow incident creation failed: {exc}") from exc

    result = response.json()["result"]
    return IncidentResult(
        incident_number=result["number"], sys_id=result["sys_id"], urgency=urgency
    )
