import structlog
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_generates_correlation_id_when_absent() -> None:
    response = client.get("/health")
    assert "X-Request-ID" in response.headers


def test_echoes_provided_correlation_id() -> None:
    response = client.get("/health", headers={"X-Request-ID": "abc-123"})
    assert response.headers["X-Request-ID"] == "abc-123"


def test_binds_correlation_id_to_log_context() -> None:
    with structlog.testing.capture_logs(
        processors=[structlog.contextvars.merge_contextvars]
    ) as captured:
        client.get("/health", headers={"X-Request-ID": "test-corr-id"})

    assert any(entry.get("correlation_id") == "test-corr-id" for entry in captured)
