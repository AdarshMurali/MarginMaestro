"""MM-146: Firebase custom tokens -- the caller's row-level-security scope
becomes the token's claims (firestore.rules checks them), and GET
/realtime/token is authenticated, off unless REALTIME=firestore, and fails
soft (503) so the frontend keeps polling."""

import base64
import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.auth import Identity, require_user
from api.main import app
from config.settings import Settings
from realtime.tokens import (
    FIREBASE_AUDIENCE,
    TOKEN_TTL_SECONDS,
    CustomTokenMinter,
    custom_token_payload,
    scope_claims,
)

client = TestClient(app)
SIGNER = "mm-api-sa@marginmaestro-demo.iam.gserviceaccount.com"


class FakeSigner:
    key_id = None

    def __init__(self) -> None:
        self.messages: list[bytes] = []

    def sign(self, message: bytes | str) -> bytes:
        self.messages.append(message if isinstance(message, bytes) else message.encode())
        return b"signature"


def _segment(token: str, index: int) -> dict:
    part = token.split(".")[index]
    return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))


# --- claims ---------------------------------------------------------------------


def test_firm_wide_scope_is_a_firm_wide_claim():
    assert scope_claims("*") == {"firm_wide": True, "cps": []}


def test_scoped_user_gets_their_counterparties():
    assert scope_claims("CP-1,CP-2") == {"firm_wide": False, "cps": ["CP-1", "CP-2"]}


def test_user_without_access_rows_sees_nothing():
    assert scope_claims("") == {"firm_wide": False, "cps": []}


# --- the token ------------------------------------------------------------------


def test_payload_is_a_firebase_custom_token():
    payload = custom_token_payload(SIGNER, "analyst1", {"cps": ["CP-1"]}, now=1_000)

    assert payload == {
        "iss": SIGNER,
        "sub": SIGNER,
        "aud": FIREBASE_AUDIENCE,
        "iat": 1_000,
        "exp": 1_000 + TOKEN_TTL_SECONDS,
        "uid": "analyst1",
        "claims": {"cps": ["CP-1"]},
    }


@pytest.mark.parametrize("uid", ["", "u" * 129])
def test_uid_must_fit_firebase_limits(uid):
    with pytest.raises(ValueError, match="uid"):
        custom_token_payload(SIGNER, uid, {})


def test_minter_signs_an_rs256_jwt_with_the_given_signer():
    signer = FakeSigner()

    token = CustomTokenMinter(SIGNER, signer).mint("analyst1", scope_claims("CP-3"))

    assert _segment(token, 0)["alg"] == "RS256"
    body = _segment(token, 1)
    assert body["uid"] == "analyst1"
    assert body["iss"] == SIGNER
    assert body["claims"] == {"firm_wide": False, "cps": ["CP-3"]}
    assert len(signer.messages) == 1


# --- GET /realtime/token -----------------------------------------------------------


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def _as(role: str, username: str = "analyst1"):
    app.dependency_overrides[require_user] = lambda: Identity(username=username, role=role)


def test_disabled_realtime_is_503():
    with patch("api.main.get_settings", return_value=_settings(realtime="none")):
        response = client.get("/realtime/token")

    assert response.status_code == 503


def test_token_claims_follow_the_callers_scope():
    _as("viewer")
    minter = MagicMock()
    minter.mint.return_value = "signed-token"
    with (
        patch("api.main.get_settings", return_value=_settings(realtime="firestore")),
        patch("api.main.get_db_session_factory", return_value=MagicMock()),
        patch("api.main.scope_for", return_value="CP-1,CP-4") as scope_for,
        patch("api.main.get_token_minter", return_value=minter),
    ):
        response = client.get("/realtime/token")

    assert response.status_code == 200
    assert response.json() == {
        "token": "signed-token",
        "collection": "margin_call_status",
        "firm_wide": False,
        "counterparty_ids": ["CP-1", "CP-4"],
        "expires_in": TOKEN_TTL_SECONDS,
    }
    assert scope_for.call_args.args[:2] == ("viewer", "analyst1")
    minter.mint.assert_called_once_with("analyst1", {"firm_wide": False, "cps": ["CP-1", "CP-4"]})


def test_firm_wide_roles_get_a_firm_wide_token():
    _as("approver", "approver")
    minter = MagicMock()
    minter.mint.return_value = "signed-token"
    with (
        patch("api.main.get_settings", return_value=_settings(realtime="firestore")),
        patch("api.main.get_db_session_factory", return_value=MagicMock()),
        patch("api.main.get_token_minter", return_value=minter),
    ):
        response = client.get("/realtime/token")

    assert response.json()["firm_wide"] is True
    assert response.json()["counterparty_ids"] == []


def test_a_signing_failure_is_503_not_500():
    minter = MagicMock()
    minter.mint.side_effect = RuntimeError("iamcredentials unavailable")
    with (
        patch("api.main.get_settings", return_value=_settings(realtime="firestore")),
        patch("api.main.get_db_session_factory", return_value=MagicMock()),
        patch("api.main.scope_for", return_value="*"),
        patch("api.main.get_token_minter", return_value=minter),
    ):
        response = client.get("/realtime/token")

    assert response.status_code == 503


def test_a_missing_signer_is_503():
    from api.main import get_token_minter

    get_token_minter.cache_clear()
    try:
        with (
            patch("api.main.get_settings", return_value=_settings(realtime="firestore")),
            patch("api.main.get_db_session_factory", return_value=MagicMock()),
            patch("api.main.scope_for", return_value="*"),
        ):
            response = client.get("/realtime/token")
    finally:
        get_token_minter.cache_clear()

    assert response.status_code == 503
    assert "FIREBASE_TOKEN_SIGNER" in response.json()["detail"]


def test_no_token_is_401(no_user_override):
    with patch(
        "api.auth.get_settings",
        return_value=_settings(auth_backend_secret="s" * 32, realtime="firestore"),
    ):
        assert client.get("/realtime/token").status_code == 401


def test_the_minter_signs_as_the_configured_account():
    from api.main import get_token_minter

    get_token_minter.cache_clear()
    try:
        with patch(
            "api.main.get_settings",
            return_value=_settings(realtime="firestore", firebase_token_signer=SIGNER),
        ):
            minter = get_token_minter()
    finally:
        get_token_minter.cache_clear()

    assert isinstance(minter, CustomTokenMinter)


def test_without_a_signer_the_minter_uses_iam_sign_blob():
    signer = FakeSigner()
    credentials = MagicMock()
    with (
        patch("google.auth.default", return_value=(credentials, "marginmaestro-demo")),
        patch("google.auth.iam.Signer", return_value=signer) as iam_signer,
    ):
        CustomTokenMinter(SIGNER).mint("approver", scope_claims("*"))

    assert iam_signer.call_args.args[1:] == (credentials, SIGNER)
    assert len(signer.messages) == 1
