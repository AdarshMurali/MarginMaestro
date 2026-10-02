"""MM-120: POST /internal/prices/refresh -- the scheduled live-price publish."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.main import app
from config.settings import Settings
from streaming.market_feed import MarketDataUnavailableError

URL = "/internal/prices/refresh"
TOKEN = "job-token"


@pytest.fixture
def client():
    return TestClient(app)


def _settings(token: str | None = TOKEN) -> Settings:
    return Settings(_env_file=None, internal_job_token=token)


def _post(client, settings: Settings, headers: dict[str, str] | None = None):
    with (
        patch("api.auth.get_settings", return_value=settings),
        patch("api.main.get_settings", return_value=settings),
        patch("api.main.publish_live_prices", return_value=30) as publish,
    ):
        return client.post(URL, headers=headers or {}), publish


def test_publishes_the_market_universe_with_the_right_token(client):
    settings = _settings()
    response, publish = _post(client, settings, {"Authorization": f"Bearer {TOKEN}"})

    assert response.status_code == 200
    assert response.json() == {"published": 30}
    publish.assert_called_once_with(settings.market_universe_list, settings=settings)


@pytest.mark.parametrize(
    "headers", [{}, {"Authorization": "Bearer wrong"}, {"Authorization": TOKEN}]
)
def test_rejects_a_missing_or_wrong_token(client, headers):
    response, publish = _post(client, _settings(), headers)

    assert response.status_code == 401
    publish.assert_not_called()


def test_disabled_when_no_token_is_configured(client):
    response, publish = _post(client, _settings(token=None), {"Authorization": "Bearer "})

    assert response.status_code == 503
    publish.assert_not_called()


def test_a_user_session_token_is_not_a_job_token(client):
    """An approver's JWT must not run internal jobs."""
    response, _ = _post(client, _settings(), {"Authorization": "Bearer eyJhbGciOi.user.jwt"})

    assert response.status_code == 401


def test_feed_outage_is_a_503(client):
    settings = _settings()
    with (
        patch("api.auth.get_settings", return_value=settings),
        patch("api.main.get_settings", return_value=settings),
        patch(
            "api.main.publish_live_prices",
            side_effect=MarketDataUnavailableError("yfinance could not price: MU"),
        ),
    ):
        response = client.post(URL, headers={"Authorization": f"Bearer {TOKEN}"})

    assert response.status_code == 503
    assert "MU" in response.json()["detail"]
