from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.auth import require_approver
from api.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _authenticated_as_approver():
    """These tests exercise each endpoint's own logic, not role-gating --
    that's covered separately in tests/unit/test_auth.py against the real
    (non-overridden) dependency."""
    app.dependency_overrides[require_approver] = lambda: "test-approver"
    yield
    app.dependency_overrides.pop(require_approver, None)


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


class TestRespondToMarginCall:
    def test_resumes_with_a_responded_signal(self) -> None:
        with (
            patch("api.main.get_orchestrator_graph", return_value=MagicMock()) as mock_get_graph,
            patch("api.main.resume_run", return_value={"sla_outcome": "met"}) as mock_resume,
        ):
            response = client.post("/margin-calls/evt-1:CP-1/respond")

        assert response.status_code == 200
        assert response.json() == {"thread_id": "evt-1:CP-1", "sla_outcome": "met"}
        mock_resume.assert_called_once_with(
            mock_get_graph.return_value, "evt-1:CP-1", {"responded": True}
        )


class TestCheckMarginCallSla:
    def test_resumes_with_a_check_signal(self) -> None:
        with (
            patch("api.main.get_orchestrator_graph", return_value=MagicMock()) as mock_get_graph,
            patch("api.main.resume_run", return_value={"sla_outcome": "breached"}) as mock_resume,
        ):
            response = client.post("/margin-calls/evt-1:CP-1/check-sla")

        assert response.status_code == 200
        assert response.json() == {"thread_id": "evt-1:CP-1", "sla_outcome": "breached"}
        mock_resume.assert_called_once_with(
            mock_get_graph.return_value, "evt-1:CP-1", {"check": True}
        )

    def test_still_pending_returns_null_outcome(self) -> None:
        with (
            patch("api.main.get_orchestrator_graph", return_value=MagicMock()),
            patch("api.main.resume_run", return_value={"__interrupt__": []}),
        ):
            response = client.post("/margin-calls/evt-1:CP-1/check-sla")

        assert response.status_code == 200
        assert response.json()["sla_outcome"] is None
