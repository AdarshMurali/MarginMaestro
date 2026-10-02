"""Cloud SQL IAM database login (MM-123): the runtime service account logs in
to Postgres as itself, with a short-lived OAuth token as the password -- no
database password exists to store or rotate. Works through Cloud Run's
built-in Cloud SQL connection (a Unix socket under /cloudsql/), which already
encrypts the link and checks IAM; the IAM database users and their `mm_app`
grants come from infra/gcp/cloud_sql.tf and scripts/cloudsql_bootstrap.ps1.

Selected with DB_AUTH=iam; DB_USER is the IAM database user, e.g.
`mm-api-sa@marginmaestro-demo.iam`. Uses google-auth (already a dependency
of the Google client libraries), so no new package.
"""

import threading
from typing import Any

from sqlalchemy import Engine, event

SQL_LOGIN_SCOPE = "https://www.googleapis.com/auth/sqlservice.login"


class IamTokenProvider:
    """Hands out a valid access token, refreshing it shortly before expiry.
    Thread-safe: the connection pool may open connections concurrently."""

    def __init__(self, credentials: Any | None = None) -> None:
        self._credentials = credentials
        self._lock = threading.Lock()

    def token(self) -> str:
        with self._lock:
            if self._credentials is None:
                from google.auth import default

                self._credentials, _ = default(scopes=[SQL_LOGIN_SCOPE])
            if not self._credentials.valid:
                from google.auth.transport.requests import Request

                self._credentials.refresh(Request())
            return str(self._credentials.token)


def use_iam_login(engine: Engine, provider: IamTokenProvider | None = None) -> None:
    """Every new physical connection gets a fresh token as its password.
    Pooled connections stay logged in after the token expires."""
    provider = provider or IamTokenProvider()

    @event.listens_for(engine, "do_connect")
    def _token_password(dialect: Any, conn_rec: Any, cargs: Any, cparams: dict) -> None:
        cparams["password"] = provider.token()
