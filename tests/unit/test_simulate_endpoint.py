from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from api.main import app
from api.schemas import SimulatedCounterpartyResult, SimulateEventResponse

client = TestClient(app)


class TestSimulateEndpoint:
    def test_returns_the_result_from_trigger_simulation(self) -> None:
        canned = SimulateEventResponse(
            scenario="price_shock",
            reason="Simulated price_shock on TSLA, NVDA",
            affected_counterparties=[
                SimulatedCounterpartyResult(
                    counterparty_id="CP-1",
                    thread_id="sim-abc:CP-1",
                    breached=True,
                    call_amount=100_000.0,
                )
            ],
        )
        session_factory = MagicMock()
        session_factory.return_value.__enter__.return_value = MagicMock()
        with (
            patch("api.main.get_db_session_factory", return_value=session_factory),
            patch("api.main.trigger_simulation", return_value=canned) as mock_trigger,
        ):
            response = client.post("/simulate", json={"scenario": "price_shock"})

        assert response.status_code == 200
        body = response.json()
        assert body["scenario"] == "price_shock"
        assert len(body["affected_counterparties"]) == 1
        mock_trigger.assert_called_once()

    def test_rejects_an_unsupported_scenario(self) -> None:
        response = client.post("/simulate", json={"scenario": "downgrade"})

        assert response.status_code == 422
