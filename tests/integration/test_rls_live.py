"""MM-107: row-level security isolation against a real Postgres (the policies
from migration b7d2f4a8c613 + persistence.db.rls).

Runs only with DB_DIALECT=postgres and a migrated database. CI's `migrations`
job runs it with REQUIRE_DB=1 (unreachable DB fails instead of skipping).
Locally: `docker compose up -d postgres`, set the Postgres DB_* env vars,
`alembic upgrade head`, then `pytest tests/integration/test_rls_live.py`.

Uses its own counterparties (RLS-A, RLS-B) and removes them afterwards, so
seeded demo data is untouched.
"""

import os
import time
from collections.abc import Iterator
from datetime import UTC, date, datetime
from unittest.mock import patch

import jwt
import pytest
from sqlalchemy import delete, text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.orm import Session, sessionmaker

from config.settings import Settings, get_settings
from persistence.db.engine import db_dialect, get_session_factory
from persistence.db.models import (
    AuditLogORM,
    CheckpointORM,
    CheckpointWriteORM,
    CollateralItemORM,
    CounterpartyORM,
    PortfolioORM,
    PositionORM,
    RatingORM,
    TicketORM,
    UserCounterpartyAccessORM,
    UserORM,
)
from persistence.db.rls import RLS_SCOPE_KEY

A, B = "RLS-A", "RLS-B"
CORRELATION = "mm107-rls-test"
THREAD = {A: f"mm107evt:{A}", B: f"mm107evt:{B}"}

# table -> SQL returning the counterparty id of each *test* row in it
TEST_ROWS = {
    "counterparties": "SELECT id FROM counterparties WHERE id LIKE 'RLS-%'",
    "portfolios": "SELECT counterparty_id FROM portfolios WHERE id LIKE 'RLS-%'",
    "positions": (
        "SELECT pf.counterparty_id FROM positions p "
        "JOIN portfolios pf ON pf.id = p.portfolio_id WHERE p.id LIKE 'RLS-%'"
    ),
    "ratings": "SELECT counterparty_id FROM ratings WHERE id LIKE 'RLS-%'",
    "collateral_items": "SELECT counterparty_id FROM collateral_items WHERE id LIKE 'RLS-%'",
    "tickets": "SELECT counterparty_id FROM tickets WHERE external_ref = 'mm107'",
    "audit_log": (
        "SELECT counterparty_id FROM audit_log "
        f"WHERE correlation_id = '{CORRELATION}' AND counterparty_id IS NOT NULL"
    ),
    "orchestrator_checkpoints": (
        "SELECT substring(thread_id from '[^:]*$') FROM orchestrator_checkpoints "
        "WHERE thread_id LIKE 'mm107evt:%'"
    ),
    "orchestrator_checkpoint_writes": (
        "SELECT substring(thread_id from '[^:]*$') FROM orchestrator_checkpoint_writes "
        "WHERE thread_id LIKE 'mm107evt:%'"
    ),
}


@pytest.fixture(scope="module")
def factory() -> sessionmaker[Session]:
    settings = get_settings()
    if db_dialect(settings) != "postgres":
        pytest.skip("row-level security is Postgres-only (set DB_DIALECT=postgres)")
    session_factory = get_session_factory(settings)
    try:
        with session_factory() as session:
            session.execute(text("SELECT app_can_see('x')"))
    except DBAPIError as exc:
        if os.environ.get("REQUIRE_DB") == "1":
            raise
        pytest.skip(f"No migrated Postgres reachable: {exc}")
    return session_factory


def _cleanup(session: Session) -> None:
    session.execute(
        delete(CheckpointWriteORM).where(CheckpointWriteORM.thread_id.like("mm107evt:%"))
    )
    session.execute(delete(CheckpointORM).where(CheckpointORM.thread_id.like("mm107evt:%")))
    session.execute(delete(AuditLogORM).where(AuditLogORM.correlation_id == CORRELATION))
    session.execute(
        delete(UserCounterpartyAccessORM).where(
            UserCounterpartyAccessORM.username == "mm107-analyst"
        )
    )
    session.execute(delete(UserORM).where(UserORM.username == "mm107-analyst"))
    session.execute(delete(TicketORM).where(TicketORM.external_ref == "mm107"))
    session.execute(delete(PositionORM).where(PositionORM.id.like("RLS-%")))
    for model in (PortfolioORM, RatingORM, CollateralItemORM):
        session.execute(delete(model).where(model.id.like("RLS-%")))
    session.execute(delete(CounterpartyORM).where(CounterpartyORM.id.like("RLS-%")))
    session.commit()


@pytest.fixture(scope="module", autouse=True)
def seeded(factory) -> Iterator[None]:
    now = datetime.now(UTC)
    with factory() as session:  # internal session: firm-wide
        _cleanup(session)
        for cp in (A, B):
            session.add(CounterpartyORM(id=cp, name=f"Test {cp}", type="Hedge Fund", country="US"))
        session.flush()
        for cp in (A, B):
            session.add_all(
                [
                    PortfolioORM(id=f"{cp}-PF", counterparty_id=cp),
                    RatingORM(
                        id=f"{cp}-RT", counterparty_id=cp, grade="A", rating_date=date(2026, 9, 1)
                    ),
                    CollateralItemORM(
                        id=f"{cp}-COL",
                        counterparty_id=cp,
                        collateral_type="cash",
                        value_usd=1_000_000.0,
                        haircut_pct=0.0,
                    ),
                    TicketORM(
                        counterparty_id=cp, status="open", external_ref="mm107", created_at=now
                    ),
                    AuditLogORM(
                        correlation_id=CORRELATION,
                        counterparty_id=cp,
                        event_type="test",
                        created_at=now,
                    ),
                    CheckpointORM(
                        thread_id=THREAD[cp],
                        checkpoint_ns="",
                        checkpoint_id="c1",
                        checkpoint_type="t",
                        checkpoint_blob=b"x",
                        metadata_type="t",
                        metadata_blob=b"x",
                        created_at=now,
                    ),
                    CheckpointWriteORM(
                        thread_id=THREAD[cp],
                        checkpoint_ns="",
                        checkpoint_id="c1",
                        task_id="t1",
                        idx=0,
                        channel="c",
                        write_type="t",
                        write_blob=b"x",
                    ),
                ]
            )
        session.flush()
        for cp in (A, B):
            session.add(
                PositionORM(
                    id=f"{cp}-POS",
                    portfolio_id=f"{cp}-PF",
                    ticker="AAPL",
                    asset_class="equity",
                    quantity=10.0,
                    trade_date=date(2026, 9, 1),
                )
            )
        # System-level audit row: no counterparty.
        session.add(
            AuditLogORM(
                correlation_id=CORRELATION,
                counterparty_id=None,
                event_type="system",
                created_at=now,
            )
        )
        session.add(UserORM(username="mm107-analyst", password_hash="x", role="viewer"))
        session.flush()
        session.add(UserCounterpartyAccessORM(username="mm107-analyst", counterparty_id=A))
        session.commit()
    yield
    with factory() as session:
        _cleanup(session)


def _scoped(factory: sessionmaker[Session], scope: str) -> Session:
    return factory(info={RLS_SCOPE_KEY: scope})


def _visible(factory, scope: str, table: str) -> list[str]:
    with _scoped(factory, scope) as session:
        return sorted(session.execute(text(TEST_ROWS[table])).scalars().all())


# --- reads ---------------------------------------------------------------------


@pytest.mark.parametrize("table", sorted(TEST_ROWS))
def test_scoped_user_sees_only_their_counterparty(factory, table):
    assert _visible(factory, A, table) == [A]


@pytest.mark.parametrize("table", sorted(TEST_ROWS))
def test_firm_wide_scope_sees_every_counterparty(factory, table):
    assert _visible(factory, "*", table) == [A, B]


@pytest.mark.parametrize("table", sorted(TEST_ROWS))
def test_empty_scope_sees_nothing_at_all(factory, table):
    with _scoped(factory, "") as session:
        whole_table = session.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
    assert whole_table == 0


def test_scope_lists_multiple_counterparties(factory):
    assert _visible(factory, f"{A},{B}", "collateral_items") == [A, B]


def test_system_level_audit_rows_are_firm_wide_only(factory):
    query = text(
        "SELECT count(*) FROM audit_log WHERE correlation_id = :c AND counterparty_id IS NULL"
    )
    with _scoped(factory, A) as session:
        assert session.execute(query, {"c": CORRELATION}).scalar_one() == 0
    with _scoped(factory, "*") as session:
        assert session.execute(query, {"c": CORRELATION}).scalar_one() == 1


def test_scope_is_not_a_prefix_match(factory):
    assert _visible(factory, "RLS-", "counterparties") == []


# --- writes --------------------------------------------------------------------


def test_cannot_insert_rows_for_another_counterparty(factory):
    with _scoped(factory, A) as session:
        session.add(
            CollateralItemORM(
                id="RLS-B-SNEAK",
                counterparty_id=B,
                collateral_type="cash",
                value_usd=1.0,
                haircut_pct=0.0,
            )
        )
        with pytest.raises(ProgrammingError, match="row-level security"):
            session.flush()


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE collateral_items SET value_usd = 0 WHERE id = 'RLS-B-COL'",
        "DELETE FROM ratings WHERE id = 'RLS-B-RT'",
        "UPDATE counterparties SET name = 'hijacked' WHERE id = 'RLS-B'",
        "DELETE FROM audit_log WHERE correlation_id = 'mm107-rls-test' AND counterparty_id = 'RLS-B'",
    ],
)
def test_cannot_update_or_delete_another_counterpartys_rows(factory, statement):
    with _scoped(factory, A) as session:
        assert session.execute(text(statement)).rowcount == 0
        session.rollback()
    assert _visible(factory, "*", "counterparties") == [A, B]


def test_cannot_move_own_row_to_another_counterparty(factory):
    with (
        _scoped(factory, A) as session,
        pytest.raises(ProgrammingError, match="row-level security"),
    ):
        session.execute(text("UPDATE ratings SET counterparty_id = 'RLS-B' WHERE id = 'RLS-A-RT'"))


def test_can_update_own_rows(factory):
    with _scoped(factory, A) as session:
        assert (
            session.execute(text("UPDATE ratings SET grade = 'AA' WHERE id = 'RLS-A-RT'")).rowcount
            == 1
        )
        session.rollback()


# --- crafted queries -----------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        # classic injection-shaped predicate
        "SELECT id FROM counterparties WHERE id = 'RLS-B' OR 1=1",
        # reach B through a global (non-RLS) table
        "SELECT DISTINCT c.id FROM price_history ph RIGHT JOIN counterparties c ON true",
        # aggregates and subqueries
        "SELECT id FROM counterparties WHERE id IN (SELECT counterparty_id FROM collateral_items)",
        "SELECT counterparty_id FROM portfolios UNION SELECT counterparty_id FROM ratings",
        # positions of B via B's portfolio id
        (
            "SELECT pf.counterparty_id FROM positions p JOIN portfolios pf ON pf.id = p.portfolio_id "
            "WHERE p.portfolio_id = 'RLS-B-PF' OR p.portfolio_id = 'RLS-A-PF'"
        ),
    ],
)
def test_crafted_sql_never_returns_another_counterparty(factory, sql):
    with _scoped(factory, A) as session:
        rows = [
            r for r in session.execute(text(sql)).scalars().all() if r and str(r).startswith("RLS-")
        ]
    assert B not in rows


def test_positions_of_another_book_are_invisible_even_by_id(factory):
    with _scoped(factory, A) as session:
        assert (
            session.execute(
                text("SELECT count(*) FROM positions WHERE id = 'RLS-B-POS'")
            ).scalar_one()
            == 0
        )


# --- through the API -----------------------------------------------------------

SECRET = "mm107-test-backend-secret-32bytes!!"


@pytest.fixture
def api_client():
    from fastapi.testclient import TestClient

    from api.main import app

    with patch(
        "api.auth.get_settings", return_value=Settings(_env_file=None, auth_backend_secret=SECRET)
    ):
        yield TestClient(app)


def _headers(username: str, role: str) -> dict[str, str]:
    token = jwt.encode(
        {"sub": username, "role": role, "exp": int(time.time()) + 60}, SECRET, algorithm="HS256"
    )
    return {"Authorization": f"Bearer {token}"}


def test_api_counterparty_list_is_scoped_by_the_database(api_client):
    response = api_client.get("/counterparties", headers=_headers("mm107-analyst", "viewer"))

    assert response.status_code == 200
    ids = {c["counterparty_id"] for c in response.json()["counterparties"]}
    assert A in ids
    assert B not in ids
    assert not any(i.startswith("CP-") for i in ids)  # seeded demo data is other analysts' too


@pytest.mark.parametrize("path_cp", [B, f"{B}' OR '1'='1", f"{A}' OR counterparty_id='{B}"])
def test_api_path_injection_cannot_reach_another_book(api_client, path_cp):
    response = api_client.get(f"/exposure/{path_cp}", headers=_headers("mm107-analyst", "viewer"))

    assert response.status_code == 404
