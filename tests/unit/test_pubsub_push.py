"""MM-121: POST /internal/pubsub/push -- Pub/Sub push target -- and the
internal-caller auth (job token or Google-signed OIDC token)."""

import base64
from datetime import UTC, date, datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from google.auth.exceptions import TransportError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from agents.orchestrator import build_orchestrator_graph
from api.main import app
from config.settings import Settings
from persistence.audit import list_audit_events
from persistence.db.models import (
    Base,
    CollateralItemORM,
    CounterpartyORM,
    PortfolioORM,
    PositionORM,
    PriceHistoryORM,
    ReferenceRateORM,
)
from rag.models import CSATermsResult
from streaming.market_feed import PriceQuote
from streaming.schemas import ImpactSet, MarketEventType

URL = "/internal/pubsub/push"
INVOKER = "mm-invoker-sa@marginmaestro-demo.iam.gserviceaccount.com"
AUDIENCE = "https://api.example.run.app"


@pytest.fixture
def client():
    return TestClient(app)


def _envelope(data: bytes, subscription: str, ordering_key: str = "") -> dict:
    return {
        "message": {
            "data": base64.b64encode(data).decode(),
            "messageId": "123",
            "orderingKey": ordering_key,
        },
        "subscription": f"projects/marginmaestro-demo/subscriptions/{subscription}",
    }


def _oidc_settings(**overrides) -> Settings:
    return Settings(
        _env_file=None,
        internal_caller_audience=AUDIENCE,
        internal_caller_service_account=INVOKER,
        **overrides,
    )


def _post(client, settings, body, token="google-token", verify=None):
    with (
        patch("api.auth.get_settings", return_value=settings),
        patch("api.main.get_settings", return_value=settings),
        patch("api.auth._verify_google_token", side_effect=verify) as verifier,
        patch("api.main.get_db_session_factory"),
        patch("api.main.get_push_event_bus"),
        patch("api.main.dispatch") as dispatch,
    ):
        response = client.post(URL, json=body, headers={"Authorization": f"Bearer {token}"})
    return response, dispatch, verifier


def _valid(token, audience):
    return {"email": INVOKER, "email_verified": True, "aud": audience}


# --- auth ---------------------------------------------------------------------


def test_a_valid_google_token_for_the_invoker_is_accepted(client):
    body = _envelope(b'{"ticker":"MU"}', "event-agent.market.prices", "MU")
    response, dispatch, verifier = _post(client, _oidc_settings(), body, verify=_valid)

    assert response.status_code == 204
    assert verifier.call_args.args == ("google-token", AUDIENCE)
    inbound = dispatch.call_args.args[0]
    assert (inbound.topic(), inbound.key(), inbound.value()) == (
        "market.prices",
        b"MU",
        b'{"ticker":"MU"}',
    )


@pytest.mark.parametrize(
    "claims",
    [
        {"email": "someone-else@x.iam.gserviceaccount.com", "email_verified": True},
        {"email": INVOKER, "email_verified": False},
        {"email": INVOKER},
    ],
)
def test_other_identities_are_rejected(client, claims):
    body = _envelope(b"{}", "event-agent.market.prices")
    response, dispatch, _ = _post(client, _oidc_settings(), body, verify=lambda t, a: claims)

    assert response.status_code == 401
    dispatch.assert_not_called()


def test_an_invalid_token_is_rejected(client):
    def bad(token, audience):
        raise ValueError("Token has wrong audience")

    response, dispatch, _ = _post(client, _oidc_settings(), _envelope(b"{}", "x"), verify=bad)

    assert response.status_code == 401
    dispatch.assert_not_called()


def test_google_keys_unreachable_is_retryable(client):
    def down(token, audience):
        raise TransportError("no route")

    response, _, _ = _post(client, _oidc_settings(), _envelope(b"{}", "x"), verify=down)

    assert response.status_code == 503  # Pub/Sub retries


def test_the_job_token_works_without_calling_google(client):
    settings = _oidc_settings(internal_job_token="local-token")
    body = _envelope(b"{}", "event-agent.market.events")
    response, _, verifier = _post(client, settings, body, token="local-token")

    assert response.status_code == 204
    verifier.assert_not_called()


def test_disabled_without_any_caller_configured(client):
    response, dispatch, _ = _post(client, Settings(_env_file=None), _envelope(b"{}", "x"))

    assert response.status_code == 503
    dispatch.assert_not_called()


def test_refresh_endpoint_accepts_the_scheduler_identity_too(client):
    settings = _oidc_settings()
    with (
        patch("api.auth.get_settings", return_value=settings),
        patch("api.main.get_settings", return_value=settings),
        patch("api.auth._verify_google_token", side_effect=_valid),
        patch("api.main.publish_live_prices", return_value=30),
    ):
        response = client.post(
            "/internal/prices/refresh", headers={"Authorization": "Bearer google-token"}
        )

    assert response.json() == {"published": 30}


# --- envelope -----------------------------------------------------------------


def test_unknown_subscription_is_a_400(client):
    response, dispatch, _ = _post(client, _oidc_settings(), _envelope(b"{}", "nope"), verify=_valid)

    assert response.status_code == 400
    dispatch.assert_not_called()


def test_non_base64_data_is_a_400(client):
    body = _envelope(b"{}", "event-agent.market.prices")
    body["message"]["data"] = "***not base64***"
    response, dispatch, _ = _post(client, _oidc_settings(), body, verify=_valid)

    assert response.status_code == 400
    dispatch.assert_not_called()


def test_a_consumer_failure_is_a_5xx_so_pubsub_redelivers(client):
    settings = _oidc_settings()
    body = _envelope(b"{}", "orchestrator.market.impact")
    with (
        patch("api.auth.get_settings", return_value=settings),
        patch("api.main.get_settings", return_value=settings),
        patch("api.auth._verify_google_token", side_effect=_valid),
        patch("api.main.get_db_session_factory"),
        patch("api.main.get_push_event_bus"),
        patch("api.main.dispatch", side_effect=RuntimeError("db down")),
    ):
        response = TestClient(app, raise_server_exceptions=False).post(
            URL, json=body, headers={"Authorization": "Bearer google-token"}
        )

    assert response.status_code == 500


# --- G4 exit criterion ---------------------------------------------------------


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        session.add(CounterpartyORM(id="CP-1", name="CP-1", type="Bank", country="US"))
        session.add(PortfolioORM(id="PF-CP-1", counterparty_id="CP-1", currency="USD"))
        session.add(
            PositionORM(
                id="POS-1",
                portfolio_id="PF-CP-1",
                ticker="TSLA",
                asset_class="equity",
                quantity=1000,
                trade_date=date(2026, 1, 1),
            )
        )
        session.add(
            PriceHistoryORM(
                ticker="TSLA",
                price_date=date(2026, 7, 30),
                price=100.0,
                currency="USD",
                source="yfinance",
            )
        )
        session.add(ReferenceRateORM(series_id="VIXCLS", rate_date=date(2026, 7, 30), value=20.0))
        session.add(
            CollateralItemORM(
                id="C1",
                counterparty_id="CP-1",
                collateral_type="cash",
                value_usd=0.0,
                haircut_pct=0.0,
            )
        )
        session.commit()
    return factory


def test_a_shock_pushed_twice_raises_exactly_one_call(client, session_factory):
    """The same impact set delivered twice runs the real orchestrator once:
    one run, paused at the approval gate (nothing sent to the client)."""
    settings = Settings(_env_file=None, internal_job_token="t")
    impact = ImpactSet(
        event_id="TSLA:2026-10-02T15:00:00+00:00:yfinance",
        event_type=MarketEventType.PRICE_SHOCK,
        counterparty_ids=["CP-1"],
        reason="TSLA moved 400.0% vs prior close",
        occurred_at=datetime(2026, 10, 2, 15, tzinfo=UTC),
    )
    feed = MagicMock()
    feed.get_prices.return_value = {
        "TSLA": PriceQuote(ticker="TSLA", price=500.0, as_of=datetime.now(UTC), source="yfinance")
    }
    graph = build_orchestrator_graph(
        session_factory=session_factory, market_feed=feed, settings=settings
    )
    csa = CSATermsResult(
        counterparty_id="CP-1",
        threshold=1_000.0,
        mta=10_000.0,
        currency="USD",
        eligible_collateral=["cash"],
        haircuts={"cash": 0.0},
        rating_triggers=[],
        citations=[],
    )
    body = _envelope(impact.model_dump_json().encode(), "orchestrator.market.impact")

    with (
        patch("api.auth.get_settings", return_value=settings),
        patch("api.main.get_settings", return_value=settings),
        patch("api.main.get_db_session_factory", return_value=session_factory),
        patch("api.main.get_push_event_bus"),
        patch("streaming.pubsub_dispatch.live_graph_factory", return_value=lambda: graph),
        patch("agents.orchestrator.answer_csa_terms", return_value=csa) as csa_agent,
    ):
        codes = [
            client.post(URL, json=body, headers={"Authorization": "Bearer t"}).status_code
            for _ in range(2)
        ]

    assert codes == [204, 204]
    csa_agent.assert_called_once()  # the LLM-backed step ran once, not twice
    with session_factory() as session:
        events = list_audit_events(session, impact.event_id, "CP-1")
    assert [e.event_type for e in events] == [
        "compute_exposure",
        "fetch_csa_terms",
        "evaluate_breach",
    ]  # each step once; await_approval's row is written when a human decides
    paused = graph.get_state({"configurable": {"thread_id": f"{impact.event_id}:CP-1"}})
    assert paused.next == ("await_approval",)
    assert paused.values["breach_result"].breached is True
