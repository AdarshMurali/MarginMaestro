from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


class TestMetricsEndpoint:
    def test_returns_prometheus_text_format(self) -> None:
        response = client.get("/metrics")

        assert response.status_code == 200
        assert "text/plain" in response.headers["content-type"]
        # A metric this module always registers, regardless of whether any
        # orchestrator run has happened yet in this test process.
        assert "marginmaestro_agent_step_total" in response.text
