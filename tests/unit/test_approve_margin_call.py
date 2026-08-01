from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


class TestApproveMarginCall:
    def test_resumes_the_graph_and_returns_the_decision(self) -> None:
        with (
            patch("api.main.get_orchestrator_graph", return_value=MagicMock()) as mock_get_graph,
            patch(
                "api.main.resume_run", return_value={"approval_decision": "approved"}
            ) as mock_resume,
        ):
            response = client.post(
                "/margin-calls/evt-1:CP-1/approve", json={"decision": "approved"}
            )

        assert response.status_code == 200
        assert response.json() == {
            "thread_id": "evt-1:CP-1",
            "approval_decision": "approved",
            "adjusted_call_amount": None,
        }
        mock_resume.assert_called_once_with(
            mock_get_graph.return_value,
            "evt-1:CP-1",
            {"decision": "approved", "adjusted_call_amount": None},
        )

    def test_passes_adjusted_call_amount_through(self) -> None:
        with (
            patch("api.main.get_orchestrator_graph", return_value=MagicMock()),
            patch(
                "api.main.resume_run",
                return_value={"approval_decision": "adjusted", "adjusted_call_amount": 5_000.0},
            ),
        ):
            response = client.post(
                "/margin-calls/evt-1:CP-1/approve",
                json={"decision": "adjusted", "adjusted_call_amount": 5_000.0},
            )

        assert response.status_code == 200
        assert response.json()["adjusted_call_amount"] == 5_000.0

    def test_rejects_invalid_decision(self) -> None:
        response = client.post("/margin-calls/evt-1:CP-1/approve", json={"decision": "maybe"})

        assert response.status_code == 422
