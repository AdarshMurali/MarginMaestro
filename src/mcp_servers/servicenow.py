from datetime import datetime
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from agents.escalation import open_servicenow_incident, retrieve_escalation_procedure

mcp = FastMCP("servicenow")


@mcp.tool()
def open_margin_call_escalation_incident(
    correlation_id: Annotated[str, Field(description="The margin-call run's correlation id.")],
    counterparty_id: Annotated[str, Field(description="The counterparty the call was made to.")],
    call_amount: Annotated[float, Field(description="The margin call amount, in `currency`.")],
    currency: Annotated[str, Field(description="ISO currency code for call_amount, e.g. 'USD'.")],
    threshold: Annotated[float, Field(description="The CSA threshold that was breached.")],
    notification_sent_at: Annotated[
        str, Field(description="ISO 8601 timestamp of when the call notice was sent.")
    ],
    deadline: Annotated[str, Field(description="ISO 8601 timestamp of the SLA deadline.")],
) -> dict:
    """Retrieve the escalation-procedures document and open a ServiceNow
    incident with full margin-call-run context (docs/adr/0007). Raises
    EscalationUnavailableError if no escalation-procedures document can be
    found, or ServiceNowError if SERVICENOW_INSTANCE_URL/USERNAME/PASSWORD
    aren't configured or the incident-creation API call fails.
    """
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
