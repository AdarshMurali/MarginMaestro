"""MM-106: row-level security plumbing (persistence.db.rls) and the API's
read-auth + scope rules. The database policies themselves are exercised
against real Postgres in MM-107's integration tests."""

import time
from unittest.mock import MagicMock, patch

import jwt
import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from api.auth import JWT_ALGORITHM, require_user
from api.main import app
from api.schemas import ExposureBoardResponse, MarginCallFeedResponse
from config.settings import Settings
from persistence.db import rls

client = TestClient(app)
SECRET = "test-backend-secret-32-bytes-long!!"


# --- scope resolution ----------------------------------------------------------


@pytest.mark.parametrize("role", ["approver", "manager", "auditor"])
def test_firm_wide_roles_see_everything_without_a_lookup(role):
    session = MagicMock()

    assert rls.scope_for(role, "someone", session) == "*"
    session.scalars.assert_not_called()


def test_scoped_user_sees_only_their_access_rows():
    session = MagicMock()
    session.scalars.return_value.all.return_value = ["CP-1", "CP-2"]

    assert rls.scope_for("viewer", "analyst1", session) == "CP-1,CP-2"


def test_user_with_no_access_rows_sees_nothing():
    session = MagicMock()
    session.scalars.return_value.all.return_value = []

    assert rls.scope_for("viewer", "nobody", session) == ""


@pytest.mark.parametrize(
    ("scope", "counterparty", "expected"),
    [
        ("*", "CP-7", True),
        ("CP-1,CP-2", "CP-2", True),
        ("CP-1,CP-2", "CP-3", False),
        ("CP-1", "CP-10", False),  # no prefix matching
        ("", "CP-1", False),
    ],
)
def test_can_see_matches_the_database_rule(scope, counterparty, expected):
    assert rls.can_see(scope, counterparty) is expected


# --- session listener ------------------------------------------------------------


def _connection(dialect: str) -> MagicMock:
    connection = MagicMock()
    connection.dialect.name = dialect
    return connection


def _executed(connection: MagicMock) -> list[tuple[str, dict | None]]:
    calls = []
    for call in connection.execute.call_args_list:
        params = call.args[1] if len(call.args) > 1 else None
        calls.append((str(call.args[0]), params))
    return calls


def test_postgres_transaction_runs_as_app_role_with_the_session_scope():
    session = MagicMock(info={rls.RLS_SCOPE_KEY: "CP-1,CP-2"})
    connection = _connection("postgresql")

    rls._apply_scope(session, MagicMock(), connection)

    assert _executed(connection) == [
        ("SET LOCAL ROLE mm_app", None),
        ("SELECT set_config('app.scope', :scope, true)", {"scope": "CP-1,CP-2"}),
    ]


def test_internal_sessions_default_to_firm_wide():
    connection = _connection("postgresql")

    rls._apply_scope(MagicMock(info={}), MagicMock(), connection)

    assert _executed(connection)[1] == (
        "SELECT set_config('app.scope', :scope, true)",
        {"scope": "*"},
    )


def test_sql_server_sessions_are_untouched():
    connection = _connection("mssql")

    rls._apply_scope(MagicMock(info={rls.RLS_SCOPE_KEY: "CP-1"}), MagicMock(), connection)

    connection.execute.assert_not_called()


# --- API: reads need a token ----------------------------------------------------

PUBLIC_GET_PATHS = {
    "/health",
    "/ready",
    "/metrics",
    "/market-universe",
    "/public/stats",
    "/openapi.json",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
}


def _depends_on_require_user(route: APIRoute) -> bool:
    return any(dep.call is require_user for dep in route.dependant.dependencies)


def test_every_non_public_read_endpoint_requires_a_user():
    """Guards the rule for endpoints added later: a new GET must either
    depend on require_user or be consciously listed as public here."""
    get_routes = [r for r in app.routes if isinstance(r, APIRoute) and "GET" in r.methods]
    unguarded = [
        r.path
        for r in get_routes
        if r.path not in PUBLIC_GET_PATHS and not _depends_on_require_user(r)
    ]

    assert unguarded == []


def _token(role: str, sub: str = "user", secret: str = SECRET) -> str:
    return jwt.encode(
        {"role": role, "sub": sub, "exp": int(time.time()) + 60}, secret, algorithm=JWT_ALGORITHM
    )


@pytest.fixture
def real_auth(no_user_override):
    with patch(
        "api.auth.get_settings", return_value=Settings(_env_file=None, auth_backend_secret=SECRET)
    ):
        yield


def _board_patches():
    session_factory = MagicMock()
    canned = ExposureBoardResponse.model_validate(
        {"as_of": "2026-01-01T00:00:00Z", "counterparties": []}
    )
    return (
        patch("api.main.get_db_session_factory", return_value=session_factory),
        patch("api.main.build_exposure_board", return_value=canned),
        session_factory,
    )


def test_read_without_token_is_401(real_auth):
    assert client.get("/exposure").status_code == 401


def test_read_with_forged_token_is_401(real_auth):
    headers = {
        "Authorization": f"Bearer {_token('approver', secret='wrong-secret-32-bytes-long!!!!!!')}"
    }

    assert client.get("/exposure", headers=headers).status_code == 401


def test_read_with_valid_token_uses_the_callers_scope(real_auth):
    factory_patch, build_patch, session_factory = _board_patches()
    with factory_patch, build_patch, patch("api.main.scope_for", return_value="CP-1,CP-2"):
        response = client.get(
            "/exposure", headers={"Authorization": f"Bearer {_token('viewer', 'analyst1')}"}
        )

    assert response.status_code == 200
    assert {"info": {rls.RLS_SCOPE_KEY: "CP-1,CP-2"}} in [
        call.kwargs for call in session_factory.call_args_list
    ]


def test_trace_outside_scope_is_404_not_403(real_auth):
    graph = MagicMock()
    with (
        patch("api.main.get_db_session_factory", return_value=MagicMock()),
        patch("api.main.scope_for", return_value="CP-1,CP-2"),
        patch("api.main.get_orchestrator_graph", return_value=graph),
    ):
        response = client.get(
            "/margin-calls/evt-1:CP-7/trace",
            headers={"Authorization": f"Bearer {_token('viewer', 'analyst1')}"},
        )

    assert response.status_code == 404
    graph.get_state.assert_not_called()


def test_audit_log_outside_scope_is_404(real_auth):
    with (
        patch("api.main.get_db_session_factory", return_value=MagicMock()),
        patch("api.main.scope_for", return_value="CP-1"),
        patch("api.main.get_margin_call_audit_log") as audit,
    ):
        response = client.get(
            "/margin-calls/evt-1:CP-5/audit-log",
            headers={"Authorization": f"Bearer {_token('viewer', 'analyst1')}"},
        )

    assert response.status_code == 404
    audit.assert_not_called()


def test_public_stats_needs_no_token_and_returns_only_counts(real_auth):
    summaries = MagicMock(counterparties=[object(), object(), object()])
    calls = MarginCallFeedResponse.model_validate(
        {"as_of": "2026-01-01T00:00:00Z", "margin_calls": []}
    )
    calls.margin_calls = [
        MagicMock(call_amount=1000.0),
        MagicMock(call_amount=0.0),
        MagicMock(call_amount=None),
    ]
    with (
        patch("api.main.get_db_session_factory", return_value=MagicMock()),
        patch("api.main.get_orchestrator_graph", return_value=MagicMock()),
        patch("api.main.list_counterparty_summaries", return_value=summaries),
        patch("api.main.list_margin_calls", return_value=calls),
    ):
        response = client.get("/public/stats")

    assert response.status_code == 200
    assert response.json() == {"counterparties": 3, "runs_evaluated": 3, "calls_raised": 1}


# --- scope can only be set in one place ----------------------------------------


def test_only_the_rls_module_sets_scope_or_role():
    """The database policies trust `app.scope` and the `mm_app` role. Any SQL
    that can set them could widen its own scope, so only
    persistence/db/rls.py may -- a guard against a future shortcut elsewhere
    (MM-107; see ADR-0011 "Limits")."""
    import re
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "src"
    # rls.py sets scope + role; grant_app_role.py is the admin tool that grants
    # role membership (MM-108) -- it never sets a transaction's scope.
    ALLOWED = {"rls.py", "grant_app_role.py"}
    pattern = re.compile(r"set_config|SET\s+(LOCAL\s+)?ROLE|RESET\s+ROLE|app\.scope", re.IGNORECASE)
    offenders = [
        str(path.relative_to(src))
        for path in src.rglob("*.py")
        if path.name not in ALLOWED and pattern.search(path.read_text(encoding="utf-8"))
    ]

    assert offenders == []
