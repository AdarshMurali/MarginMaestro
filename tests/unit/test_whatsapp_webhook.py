"""G6 (MM-133): the public WhatsApp webhook routes -- Meta's verification
handshake and the signed POST. Processing itself is covered on the real
graph in test_whatsapp_flow.py."""

import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.whatsapp_webhook import verify_signature
from config.settings import Settings

APP_SECRET = "meta-app-secret"
VERIFY = "verify-me"
URL = "/webhooks/whatsapp"


@pytest.fixture
def client():
    return TestClient(app)


def _settings(**overrides) -> Settings:
    values = {"whatsapp_app_secret": APP_SECRET, "whatsapp_verify_token": VERIFY}
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _sign(body: bytes, secret: str = APP_SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


BODY = json.dumps(
    {
        "object": "whatsapp_business_account",
        "entry": [{"changes": [{"field": "messages", "value": {"statuses": []}}]}],
    }
).encode()


# --- signature -------------------------------------------------------------------------


def test_signature_matches_meta_format():
    assert verify_signature(BODY, _sign(BODY), APP_SECRET)


@pytest.mark.parametrize(
    "header",
    [None, "", "sha1=abc", "sha256=" + "0" * 64, _sign(b"other body"), _sign(BODY, "wrong")],
)
def test_bad_or_missing_signatures_are_rejected(header):
    assert not verify_signature(BODY, header, APP_SECRET)


def test_no_app_secret_never_verifies():
    assert not verify_signature(BODY, _sign(BODY, ""), "")


# --- GET: Meta's verification handshake -----------------------------------------------


def _verify(client, settings, **params):
    with patch("api.main.get_settings", return_value=settings):
        return client.get(URL, params=params)


def test_handshake_echoes_the_challenge_for_the_right_token(client):
    response = _verify(
        client,
        _settings(),
        **{"hub.mode": "subscribe", "hub.verify_token": VERIFY, "hub.challenge": "1158201444"},
    )

    assert response.status_code == 200
    assert response.text == "1158201444"


@pytest.mark.parametrize(
    "params",
    [
        {"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "1"},
        {"hub.mode": "unsubscribe", "hub.verify_token": VERIFY, "hub.challenge": "1"},
        {"hub.challenge": "1"},
    ],
)
def test_handshake_refuses_anything_else(client, params):
    assert _verify(client, _settings(), **params).status_code == 403


def test_handshake_is_off_until_a_verify_token_is_set(client):
    response = _verify(
        client,
        _settings(whatsapp_verify_token=None),
        **{"hub.mode": "subscribe", "hub.verify_token": "x"},
    )
    assert response.status_code == 503


def test_handshake_needs_no_login(client, no_user_override):
    response = _verify(
        client,
        _settings(),
        **{"hub.mode": "subscribe", "hub.verify_token": VERIFY, "hub.challenge": "7"},
    )
    assert response.status_code == 200


# --- POST: signed events --------------------------------------------------------------


def _post(client, settings, body=BODY, signature=None, process=None):
    deps = MagicMock()
    with (
        patch("api.main.get_settings", return_value=settings),
        patch("api.main.get_whatsapp_webhook_deps", return_value=deps),
        patch("api.main.process_webhook", **(process or {"return_value": ["status_sent"]})) as run,
    ):
        response = client.post(
            URL,
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": signature if signature is not None else _sign(body),
            },
        )
    return response, run, deps


def test_signed_payload_is_processed_and_acknowledged_with_200(client):
    response, run, deps = _post(client, _settings())

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "processed": 1}
    payload, passed_deps = run.call_args.args
    assert payload.object == "whatsapp_business_account"
    assert passed_deps is deps


def test_unsigned_or_forged_payload_is_rejected_before_parsing(client):
    response, run, _ = _post(client, _settings(), signature=_sign(BODY, "forged"))

    assert response.status_code == 401
    run.assert_not_called()


def test_post_is_off_until_the_app_secret_is_set(client):
    response, run, _ = _post(client, _settings(whatsapp_app_secret=None))

    assert response.status_code == 503
    run.assert_not_called()


def test_signed_but_malformed_payload_is_a_400(client):
    body = b'{"entry": "not-a-list"}'
    response, run, _ = _post(client, _settings(), body=body)

    assert response.status_code == 400
    run.assert_not_called()


def test_unexpected_processing_error_is_a_500_so_meta_redelivers(client):
    client = TestClient(app, raise_server_exceptions=False)
    response, _, _ = _post(client, _settings(), process={"side_effect": RuntimeError("db down")})

    assert response.status_code == 500


def test_webhook_deps_are_built_from_settings():
    from api import main

    main.get_whatsapp_webhook_deps.cache_clear()
    main.get_api_internal_notifier.cache_clear()
    settings = Settings(_env_file=None)
    try:
        with (
            patch("api.main.get_settings", return_value=settings),
            patch("api.main.get_orchestrator_graph", return_value="graph"),
            patch("api.main.get_db_session_factory", return_value="sessions"),
        ):
            deps = main.get_whatsapp_webhook_deps()
    finally:
        main.get_whatsapp_webhook_deps.cache_clear()
        main.get_api_internal_notifier.cache_clear()

    assert deps.graph == "graph" and deps.session_factory == "sessions"
    assert deps.guardrail.name == "incode"
    assert deps.internal_notifier.enabled is False  # INTERNAL_NOTIFIER defaults to none
