"""MM-146 (ADR-0021): Firebase custom tokens for the frontend's Firestore
listener.

The logged-in user's row-level-security scope (persistence.db.rls.scope_for)
becomes two custom claims, which firebase/firestore.rules checks on every read
of `margin_call_status/{id}`:

- `firm_wide: true`  -- approver, manager, auditor: every counterparty.
- `cps: [...]`        -- a scoped analyst's own counterparty ids (may be empty).

The token is a JWT signed by a service account through the IAM Credentials
signBlob API (google-auth's iam.Signer) -- no key file, and no firebase-admin
dependency. On Cloud Run the signer is the API's own service account, which
needs roles/iam.serviceAccountTokenCreator on itself (infra/gcp/firebase.tf).
"""

import time
from typing import Any, Protocol

from persistence.db.rls import FIRM_WIDE

# Firebase Auth accepts custom tokens signed by a service account, with this
# audience, valid for at most one hour.
FIREBASE_AUDIENCE = (
    "https://identitytoolkit.googleapis.com/google.identity.identitytoolkit.v1.IdentityToolkit"
)
TOKEN_TTL_SECONDS = 3600
# Firebase uids are at most 128 characters.
_MAX_UID = 128


class Signer(Protocol):
    """google.auth.crypt.Signer's shape."""

    @property
    def key_id(self) -> str | None: ...

    def sign(self, message: bytes | str) -> bytes: ...


def scope_claims(scope: str) -> dict[str, Any]:
    """The custom claims for a scope_for() value (see persistence.db.rls)."""
    if scope == FIRM_WIDE:
        return {"firm_wide": True, "cps": []}
    return {"firm_wide": False, "cps": [cp for cp in scope.split(",") if cp]}


def custom_token_payload(
    signer_email: str, uid: str, claims: dict[str, Any], now: int | None = None
) -> dict[str, Any]:
    if not uid or len(uid) > _MAX_UID:
        raise ValueError("Firebase uid must be 1-128 characters")
    issued_at = int(time.time()) if now is None else now
    return {
        "iss": signer_email,
        "sub": signer_email,
        "aud": FIREBASE_AUDIENCE,
        "iat": issued_at,
        "exp": issued_at + TOKEN_TTL_SECONDS,
        "uid": uid,
        "claims": claims,
    }


class CustomTokenMinter:
    def __init__(self, signer_email: str, signer: Signer | None = None) -> None:
        self._email = signer_email
        self._signer = signer

    def _get_signer(self) -> Signer:
        if self._signer is None:
            from google.auth import default as default_credentials
            from google.auth import iam
            from google.auth.transport.requests import Request

            credentials, _ = default_credentials(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            self._signer = iam.Signer(Request(), credentials, self._email)
        return self._signer

    def mint(self, uid: str, claims: dict[str, Any]) -> str:
        from google.auth import jwt

        payload = custom_token_payload(self._email, uid, claims)
        token: bytes = jwt.encode(self._get_signer(), payload)
        return token.decode("utf-8")
