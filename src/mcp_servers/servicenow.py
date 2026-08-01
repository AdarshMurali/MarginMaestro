from datetime import datetime

from mcp.server.fastmcp import FastMCP

from agents.escalation import open_servicenow_incident, retrieve_escalation_procedure

mcp = FastMCP("servicenow")


@mcp.tool()
def open_margin_call_escalation_incident(
    correlation_id: str,
    counterparty_id: str,
    call_amount: float,
    currency: str,
    threshold: float,
    notification_sent_at: str,
    deadline: str,
) -> dict:
    """Retrieve the escalation-procedures document and open a ServiceNow
    incident with full margin-call-run context (docs/adr/0007)."""
    procedure_excerpt = retrieve_escalation_procedure()
    result = open_servicenow_incident(
        correlation_id,
        counterparty_id,
        call_amount,
        currency,
        threshold,
        datetime.fromisoformat(notification_sent_at),
        datetime.fromisoformat(deadline),
        procedure_excerpt,
    )
    return result.model_dump()


if __name__ == "__main__":
    mcp.run()
