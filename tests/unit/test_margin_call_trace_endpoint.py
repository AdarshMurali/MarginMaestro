from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from api.main import app
from api.schemas import MarginCallTraceResponse, TraceStep, TraceStepStatus

client = TestClient(app)


class TestMarginCallTraceEndpoint:
    def test_returns_the_trace_from_get_margin_call_trace(self) -> None:
        canned = MarginCallTraceResponse(
            thread_id="evt-1:CP-1",
            steps=[
                TraceStep(
                    step=0,
                    node="Event received",
                    status=TraceStepStatus.COMPLETED,
                    completed_at=datetime(2026, 1, 1, tzinfo=UTC),
                    summary="Event received: test",
                )
            ],
        )
        with (
            patch("api.main.get_orchestrator_graph", return_value=MagicMock()),
            patch("api.main.get_margin_call_trace", return_value=canned) as mock_get,
        ):
            response = client.get("/margin-calls/evt-1:CP-1/trace")

        assert response.status_code == 200
        assert response.json()["thread_id"] == "evt-1:CP-1"
        assert len(response.json()["steps"]) == 1
        mock_get.assert_called_once()

    def test_unknown_thread_returns_404(self) -> None:
        with (
            patch("api.main.get_orchestrator_graph", return_value=MagicMock()),
            patch("api.main.get_margin_call_trace", return_value=None),
        ):
            response = client.get("/margin-calls/no-such-thread/trace")

        assert response.status_code == 404
