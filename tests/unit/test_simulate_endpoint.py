from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.auth import require_approver
from api.main import app
from api.schemas import SimulatedCounterpartyResult, SimulateEventResponse

client = TestClient(app)


@pytest.fixture(autouse=True)
def _authenticated_as_approver():
    """Role-gating itself is covered separately in tests/unit/test_auth.py
    against the real (non-overridden) dependency."""
    app.dependency_overrides[require_approver] = lambda: "test-approver"
    yield
    app.dependency_overrides.pop(require_approver, None)


class TestSimulateEndpoint:
    def test_returns_the_result_from_trigger_simulation(self) -> None:
        canned = SimulateEventResponse(
            event_type="price_shock",
            reason="Simulated price_shock: TSLA -12.0%",
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
            response = client.post(
                "/simulate", json={"event_type": "price_shock", "ticker": "TSLA", "pct_change": -12}
            )

        assert response.status_code == 200
        body = response.json()
        assert body["event_type"] == "price_shock"
        assert len(body["affected_counterparties"]) == 1
        mock_trigger.assert_called_once()
        # pct_change is converted from percent to fraction before hitting trigger_simulation.
        args, _ = mock_trigger.call_args
        assert args[2] == -0.12

    def test_rejects_an_unsupported_event_type(self) -> None:
        response = client.post(
            "/simulate", json={"event_type": "downgrade", "ticker": "TSLA", "pct_change": -12}
        )

        assert response.status_code == 422

    def test_rejects_a_ticker_outside_the_market_universe(self) -> None:
        response = client.post(
            "/simulate", json={"event_type": "price_shock", "ticker": "ZZZZ", "pct_change": -12}
        )

        assert response.status_code == 400


class TestMarketUniverseEndpoint:
    def test_returns_the_curated_ticker_list(self) -> None:
        response = client.get("/market-universe")

        assert response.status_code == 200
        tickers = response.json()["tickers"]
        assert "TSLA" in tickers
        assert "NVDA" in tickers
        assert "BTC-USD" in tickers
