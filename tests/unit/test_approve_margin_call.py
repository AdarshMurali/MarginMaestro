from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.auth import require_approver, require_manager
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


def _graph_pending_at(node: str) -> MagicMock:
    """A MagicMock graph whose get_state().next reports the given node as
    the sole pending step -- _require_pending_node's happy path."""
    graph = MagicMock()
    graph.get_state.return_value.next = (node,)
    graph.get_state.return_value.values = {}
    return graph


class TestApproveMarginCall:
    def test_resumes_the_graph_and_returns_the_decision(self) -> None:
        mock_graph = _graph_pending_at("await_approval")
        with (
            patch("api.main.get_orchestrator_graph", return_value=mock_graph),
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
            mock_graph,
            "evt-1:CP-1",
            {
                "decision": "approved",
                "adjusted_call_amount": None,
                "approver_username": "test-approver",
            },
        )

    def test_passes_adjusted_call_amount_through(self) -> None:
        with (
            patch(
                "api.main.get_orchestrator_graph", return_value=_graph_pending_at("await_approval")
            ),
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

    def test_rejects_when_not_actually_awaiting_first_approval(self) -> None:
        """MM-79: reproduces the real bug found live -- calling /approve on a
        thread that's already past the first gate (e.g. paused at the
        elite-tier second signature, or already finished) must not silently
        resume whatever's actually pending."""
        with (
            patch(
                "api.main.get_orchestrator_graph",
                return_value=_graph_pending_at("await_manager_approval"),
            ),
            patch("api.main.resume_run") as mock_resume,
        ):
            response = client.post(
                "/margin-calls/evt-1:CP-1/approve", json={"decision": "approved"}
            )

        assert response.status_code == 409
        assert "await_approval" in response.json()["detail"]
        mock_resume.assert_not_called()


class TestManagerApproveMarginCall:
    def test_resumes_the_graph_and_returns_the_decision(self) -> None:
        app.dependency_overrides[require_manager] = lambda: "test-manager"
        try:
            mock_graph = _graph_pending_at("await_manager_approval")
            mock_graph.get_state.return_value.values = {"first_approver_username": "test-approver"}
            with (
                patch("api.main.get_orchestrator_graph", return_value=mock_graph),
                patch(
                    "api.main.resume_run",
                    return_value={"approval_decision": "approved", "manager_decision": "approved"},
                ) as mock_resume,
            ):
                response = client.post(
                    "/margin-calls/evt-1:CP-1/manager-approve", json={"decision": "approved"}
                )
        finally:
            app.dependency_overrides.pop(require_manager, None)

        assert response.status_code == 200
        assert response.json() == {
            "thread_id": "evt-1:CP-1",
            "approval_decision": "approved",
            "manager_decision": "approved",
        }
        mock_resume.assert_called_once_with(
            mock_graph, "evt-1:CP-1", {"decision": "approved", "manager_username": "test-manager"}
        )

    def test_same_person_as_first_approver_is_rejected(self) -> None:
        app.dependency_overrides[require_manager] = lambda: "test-approver"
        try:
            mock_graph = _graph_pending_at("await_manager_approval")
            mock_graph.get_state.return_value.values = {"first_approver_username": "test-approver"}
            with (
                patch("api.main.get_orchestrator_graph", return_value=mock_graph),
                patch("api.main.resume_run") as mock_resume,
            ):
                response = client.post(
                    "/margin-calls/evt-1:CP-1/manager-approve", json={"decision": "approved"}
                )
        finally:
            app.dependency_overrides.pop(require_manager, None)

        assert response.status_code == 403
        assert "same person" in response.json()["detail"].lower()
        mock_resume.assert_not_called()

    def test_rejects_invalid_decision(self) -> None:
        app.dependency_overrides[require_manager] = lambda: "test-manager"
        try:
            response = client.post(
                "/margin-calls/evt-1:CP-1/manager-approve", json={"decision": "adjusted"}
            )
        finally:
            app.dependency_overrides.pop(require_manager, None)

        assert response.status_code == 422

    def test_rejects_when_not_actually_awaiting_second_approval(self) -> None:
        """MM-79: reproduces the real bug found live -- calling /manager-approve
        (or, the actual bug, calling /approve a second time and having it
        land here) on a thread not actually paused at await_manager_approval
        must 409, not silently resume whatever the thread really has
        pending."""
        app.dependency_overrides[require_manager] = lambda: "test-manager"
        try:
            with (
                patch(
                    "api.main.get_orchestrator_graph",
                    return_value=_graph_pending_at("await_approval"),
                ),
                patch("api.main.resume_run") as mock_resume,
            ):
                response = client.post(
                    "/margin-calls/evt-1:CP-1/manager-approve", json={"decision": "approved"}
                )
        finally:
            app.dependency_overrides.pop(require_manager, None)

        assert response.status_code == 409
        assert "await_manager_approval" in response.json()["detail"]
        mock_resume.assert_not_called()


class TestRespondToMarginCall:
    def test_resumes_with_a_responded_signal(self) -> None:
        mock_graph = _graph_pending_at("await_sla_response")
        with (
            patch("api.main.get_orchestrator_graph", return_value=mock_graph),
            patch("api.main.resume_run", return_value={"sla_outcome": "met"}) as mock_resume,
        ):
            response = client.post("/margin-calls/evt-1:CP-1/respond")

        assert response.status_code == 200
        assert response.json() == {"thread_id": "evt-1:CP-1", "sla_outcome": "met"}
        mock_resume.assert_called_once_with(mock_graph, "evt-1:CP-1", {"responded": True})

    def test_rejects_when_not_actually_awaiting_sla_response(self) -> None:
        with (
            patch(
                "api.main.get_orchestrator_graph",
                return_value=_graph_pending_at("await_approval"),
            ),
            patch("api.main.resume_run") as mock_resume,
        ):
            response = client.post("/margin-calls/evt-1:CP-1/respond")

        assert response.status_code == 409
        mock_resume.assert_not_called()


class TestCheckMarginCallSla:
    def test_resumes_with_a_check_signal(self) -> None:
        mock_graph = _graph_pending_at("await_sla_response")
        with (
            patch("api.main.get_orchestrator_graph", return_value=mock_graph),
            patch("api.main.resume_run", return_value={"sla_outcome": "breached"}) as mock_resume,
        ):
            response = client.post("/margin-calls/evt-1:CP-1/check-sla")

        assert response.status_code == 200
        assert response.json() == {"thread_id": "evt-1:CP-1", "sla_outcome": "breached"}
        mock_resume.assert_called_once_with(mock_graph, "evt-1:CP-1", {"check": True})

    def test_still_pending_returns_null_outcome(self) -> None:
        with (
            patch(
                "api.main.get_orchestrator_graph",
                return_value=_graph_pending_at("await_sla_response"),
            ),
            patch("api.main.resume_run", return_value={"__interrupt__": []}),
        ):
            response = client.post("/margin-calls/evt-1:CP-1/check-sla")

        assert response.status_code == 200
        assert response.json()["sla_outcome"] is None

    def test_rejects_when_not_actually_awaiting_sla_response(self) -> None:
        with (
            patch(
                "api.main.get_orchestrator_graph",
                return_value=_graph_pending_at("await_manager_approval"),
            ),
            patch("api.main.resume_run") as mock_resume,
        ):
            response = client.post("/margin-calls/evt-1:CP-1/check-sla")

        assert response.status_code == 409
        mock_resume.assert_not_called()
