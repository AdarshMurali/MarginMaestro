from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from api.main import app
from api.schemas import AuditLogEntry, AuditLogResponse

client = TestClient(app)


class TestMarginCallAuditLogEndpoint:
    def test_returns_the_audit_log_from_get_margin_call_audit_log(self) -> None:
        canned = AuditLogResponse(
            thread_id="evt-1:CP-1",
            correlation_id="corr-1",
            entries=[
                AuditLogEntry(
                    event_type="compute_exposure",
                    payload={"variation_margin": {"variation_margin": 100.0}},
                    created_at=datetime(2026, 1, 1, tzinfo=UTC),
                )
            ],
        )
        with (
            patch("api.main.get_orchestrator_graph", return_value=MagicMock()),
            patch("api.main.get_margin_call_audit_log", return_value=canned) as mock_get,
        ):
            response = client.get("/margin-calls/evt-1:CP-1/audit-log")

        assert response.status_code == 200
        assert response.json()["thread_id"] == "evt-1:CP-1"
        assert response.json()["correlation_id"] == "corr-1"
        assert len(response.json()["entries"]) == 1
        mock_get.assert_called_once()

    def test_unknown_thread_returns_404(self) -> None:
        with (
            patch("api.main.get_orchestrator_graph", return_value=MagicMock()),
            patch("api.main.get_margin_call_audit_log", return_value=None),
        ):
            response = client.get("/margin-calls/no-such-thread/audit-log")

        assert response.status_code == 404
