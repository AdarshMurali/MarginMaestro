from unittest.mock import patch

import pytest

from agents.escalation import EscalationUnavailableError, IncidentResult, ServiceNowError
from mcp_servers.servicenow import open_margin_call_escalation_incident


class TestOpenMarginCallEscalationIncidentTool:
    def test_retrieves_procedure_then_opens_incident(self) -> None:
        result = IncidentResult(incident_number="INC0010001", sys_id="abc123", urgency="1")

        with (
            patch(
                "mcp_servers.servicenow.retrieve_escalation_procedure",
                return_value="mock procedure",
            ) as mock_retrieve,
            patch(
                "mcp_servers.servicenow.open_servicenow_incident", return_value=result
            ) as mock_open,
        ):
            output = open_margin_call_escalation_incident(
                "corr-1",
                "CP-1",
                474_000.0,
                "USD",
                100_000.0,
                "2026-08-01T12:00:00+00:00",
                "2026-08-01T13:00:00+00:00",
            )

        mock_retrieve.assert_called_once()
        args, _ = mock_open.call_args
        assert args[0] == "corr-1"
        assert args[7] == "mock procedure"
        assert output == result.model_dump()

    def test_escalation_unavailable_error_propagates_not_swallowed(self) -> None:
        with (
            patch(
                "mcp_servers.servicenow.retrieve_escalation_procedure",
                side_effect=EscalationUnavailableError(
                    "No escalation-procedures document chunks found"
                ),
            ),
            pytest.raises(EscalationUnavailableError),
        ):
            open_margin_call_escalation_incident(
                "corr-1",
                "CP-1",
                474_000.0,
                "USD",
                100_000.0,
                "2026-08-01T12:00:00+00:00",
                "2026-08-01T13:00:00+00:00",
            )

    def test_servicenow_error_propagates_not_swallowed(self) -> None:
        with (
            patch(
                "mcp_servers.servicenow.retrieve_escalation_procedure",
                return_value="mock procedure",
            ),
            patch(
                "mcp_servers.servicenow.open_servicenow_incident",
                side_effect=ServiceNowError("ServiceNow incident creation failed: 500"),
            ),
            pytest.raises(ServiceNowError, match="500"),
        ):
            open_margin_call_escalation_incident(
                "corr-1",
                "CP-1",
                474_000.0,
                "USD",
                100_000.0,
                "2026-08-01T12:00:00+00:00",
                "2026-08-01T13:00:00+00:00",
            )
