"""MM-57: login verification + role gating for mutating endpoints.

Two pieces, deliberately separate:
1. verify_credentials() -- called once, by POST /auth/verify, when NextAuth's
   Credentials provider checks a login attempt. The only place this backend
   ever sees a plaintext password.
2. require_approver() -- a FastAPI dependency applied to every mutating
   endpoint (approve/respond/check-sla/simulate). Verifies a short-lived JWT
   the frontend mints server-side (in NextAuth's session callback, signed
   with the same AUTH_BACKEND_SECRET) and attaches as a Bearer header --
   real enforcement, not just a hidden button. A request with no token, an
   invalid signature, or a non-"approver" role is rejected here, before the
   endpoint's own logic ever runs.
"""

import bcrypt
import jwt
from fastapi import Header, HTTPException
from sqlalchemy.orm import Session

from config.settings import get_settings
from persistence.db.models import UserORM

JWT_ALGORITHM = "HS256"


def verify_credentials(username: str, password: str, session: Session) -> str | None:
    """Returns the user's role on success, None on a bad username/password
    (deliberately not distinguishing which, same as any login form)."""
    user = session.get(UserORM, username)
    if user is None:
        return None
    if not bcrypt.checkpw(password.encode("utf-8"), user.password_hash.encode("utf-8")):
        return None
    return user.role


def _require_role(role: str, authorization: str | None) -> str:
    """Shared by require_approver/require_manager: decodes the bearer JWT
    and enforces the given role. Returns the authenticated username on
    success; raises 401/403 otherwise."""
    settings = get_settings()
    if not settings.auth_backend_secret:
        raise HTTPException(status_code=500, detail="AUTH_BACKEND_SECRET is not configured")

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")

    token = authorization.removeprefix("Bearer ")
    try:
        claims = jwt.decode(token, settings.auth_backend_secret, algorithms=[JWT_ALGORITHM])
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc

    if claims.get("role") != role:
        raise HTTPException(status_code=403, detail=f"{role.capitalize()} role required")

    username = claims.get("sub")
    if not username:
        raise HTTPException(status_code=401, detail="Token missing subject")
    return username


def require_approver(authorization: str | None = Header(default=None)) -> str:
    """Returns the authenticated username on success; raises 401/403
    otherwise. FastAPI dependency -- add as `Depends(require_approver)`."""
    return _require_role("approver", authorization)


def require_manager(authorization: str | None = Header(default=None)) -> str:
    """Second-signature role for elite-tier counterparties (Phase 9 scope
    addition) -- a distinct role from `approver`, gated the same real way
    (401/403 at the API layer, not a hidden frontend button). FastAPI
    dependency -- add as `Depends(require_manager)`."""
    return _require_role("manager", authorization)
