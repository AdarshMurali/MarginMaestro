"""MM-125: POST /internal/margin/daily-run -- the scheduled daily margin run."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from agents.margin_policy import CounterpartyBusyError, TriggerAction, TriggerOutcome
from api.main import app
from config.settings import Settings
from streaming.schemas import ImpactSet, MarketEventType

URL = "/internal/margin/daily-run"
TOKEN = "job-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client():
    return TestClient(app)


def _settings(token: str | None = TOKEN) -> Settings:
    return Settings(_env_file=None, internal_job_token=token)


def _impact() -> ImpactSet:
    return ImpactSet(
        event_id="daily-margin-run:2026-10-05",
        event_type=MarketEventType.DAILY_MARGIN_RUN,
        counterparty_ids=["CP-1", "CP-2"],
        reason="Daily margin run for 2026-10-05",
        occurred_at=datetime(2026, 10, 5, 20, 45, tzinfo=UTC),
    )


def _post(client, headers, handle):
    settings = _settings()
    with (
        patch("api.auth.get_settings", return_value=settings),
        patch("api.main.get_settings", return_value=settings),
        patch("api.main.get_db_session_factory", return_value=MagicMock()),
        patch("api.main.daily_margin_run_impact", return_value=_impact()) as build,
        patch("api.main.live_graph_factory") as graph_factory,
        patch("api.main.handle_impact", **handle) as handle_impact,
    ):
        response = client.post(URL, headers=headers)
    return response, build, graph_factory, handle_impact


def test_dispatches_every_counterparty_and_reports_each_outcome(client):
    outcomes = [
        TriggerOutcome(
            counterparty_id="CP-1",
            action=TriggerAction.STARTED,
            thread_id="daily-margin-run:2026-10-05:CP-1",
            breached=True,
            call_amount=250_785.91,
            detail="Daily margin run: ...",
        ),
        TriggerOutcome(
            counterparty_id="CP-2",
            action=TriggerAction.UNCHANGED,
            thread_id="evt:CP-2",
            detail="already approved",
        ),
    ]
    response, build, graph_factory, handle_impact = _post(client, AUTH, {"return_value": outcomes})

    assert response.status_code == 200
    body = response.json()
    assert body["event_id"] == "daily-margin-run:2026-10-05"
    assert body["counterparties"] == 2
    assert [o["action"] for o in body["outcomes"]] == ["started", "unchanged"]
    assert body["outcomes"][0]["call_amount"] == 250_785.91
    run_date = build.call_args.args[1]
    assert run_date == datetime.now(UTC).date()
    impact, _, factory = handle_impact.call_args.args
    assert impact.event_id == "daily-margin-run:2026-10-05"
    assert factory is graph_factory.return_value


def test_a_busy_counterparty_is_a_503_so_the_scheduler_retries(client):
    response, *_ = _post(client, AUTH, {"side_effect": CounterpartyBusyError("CP-1 busy")})

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "60"


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}])
def test_rejects_a_missing_or_wrong_token(client, headers):
    response, _, _, handle_impact = _post(client, headers, {"return_value": []})

    assert response.status_code == 401
    handle_impact.assert_not_called()
