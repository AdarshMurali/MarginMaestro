"""MM-137: the audit trail is append-only in the database -- migration
e3f8a1c5d927 revokes UPDATE/DELETE on audit_log from the app role `mm_app`.

Runs only with DB_DIALECT=postgres and a migrated database. CI's
`migrations` job runs it with REQUIRE_DB=1 (unreachable DB fails instead of
skipping). Locally: `docker compose up -d postgres`, the Postgres DB_* env
vars, `alembic upgrade head`, then `pytest tests/integration/test_audit_append_only_live.py`.
"""

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from config.settings import get_settings
from persistence.audit import record_audit_event
from persistence.db.engine import db_dialect, get_session_factory
from persistence.db.models import AuditLogORM

CORRELATION = "mm137-append-only"


@pytest.fixture(scope="module")
def factory() -> Iterator[sessionmaker[Session]]:
    settings = get_settings()
    if db_dialect(settings) != "postgres":
        pytest.skip("append-only grants are Postgres-only (set DB_DIALECT=postgres)")
    session_factory = get_session_factory(settings)
    try:
        with session_factory() as session:
            session.execute(text("SELECT 1 FROM audit_log LIMIT 1"))
    except DBAPIError as exc:
        if os.environ.get("REQUIRE_DB") == "1":
            raise
        pytest.skip(f"No migrated Postgres reachable: {exc}")
    yield session_factory
    # Test rows go over a plain connection as the login user (the table
    # owner): the app role itself can't delete them -- that's the point.
    with session_factory.kw["bind"].connect() as owner:
        owner.execute(text("SELECT set_config('app.scope', '*', true)"))
        owner.execute(delete(AuditLogORM).where(AuditLogORM.correlation_id == CORRELATION))
        owner.commit()


@pytest.fixture
def row_id(factory) -> int:
    with factory() as session:
        record_audit_event(session, CORRELATION, "mm137_test", {"step": 1}, "CP-1")
        return session.execute(
            select(AuditLogORM.id)
            .where(AuditLogORM.correlation_id == CORRELATION)
            .order_by(AuditLogORM.id.desc())
        ).scalar_one()


def test_app_role_holds_insert_and_select_only(factory):
    with factory() as session:
        privileges = {
            privilege: session.execute(
                text("SELECT has_table_privilege('mm_app', 'audit_log', :p)"), {"p": privilege}
            ).scalar_one()
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE")
        }
    assert privileges == {
        "SELECT": True,
        "INSERT": True,
        "UPDATE": False,
        "DELETE": False,
        "TRUNCATE": False,
    }


def test_the_app_can_append_and_read(factory, row_id):
    with factory() as session:
        row = session.get(AuditLogORM, row_id)
        assert row is not None and row.payload == {"step": 1}


@pytest.mark.parametrize(
    "statement",
    [
        lambda rid: update(AuditLogORM).where(AuditLogORM.id == rid).values(event_type="forged"),
        lambda rid: delete(AuditLogORM).where(AuditLogORM.id == rid),
    ],
    ids=["update", "delete"],
)
def test_the_app_cannot_rewrite_or_erase_history(factory, row_id, statement):
    with factory() as session, pytest.raises(DBAPIError, match="permission denied"):
        session.execute(statement(row_id))
        session.commit()


def test_orm_delete_is_refused_too(factory, row_id):
    with factory() as session:
        session.delete(session.get(AuditLogORM, row_id))
        with pytest.raises(DBAPIError, match="permission denied"):
            session.commit()


def test_the_row_is_unchanged_after_the_attempts(factory, row_id):
    for attempt in (
        update(AuditLogORM).where(AuditLogORM.id == row_id).values(payload={"step": 99}),
        delete(AuditLogORM).where(AuditLogORM.id == row_id),
    ):
        with factory() as session:
            try:
                session.execute(attempt)
                session.commit()
            except DBAPIError:
                session.rollback()
    with factory() as session:
        row = session.get(AuditLogORM, row_id)
        assert row is not None and row.payload == {"step": 1}
        assert row.event_type == "mm137_test"
