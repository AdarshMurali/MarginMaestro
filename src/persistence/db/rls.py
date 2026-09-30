"""Row-level security plumbing (MM-106, ADR-0011).

Every Postgres transaction runs as the non-owner `mm_app` role with an
`app.scope` setting that the database policies check (migration
b7d2f4a8c613). Scope values:

- `*` -- firm-wide: approver, manager, auditor, and internal jobs
  (orchestrator, event agent, loaders). Also the default for sessions that
  don't set one: those are internal workers, never an external caller.
- `CP-1,CP-2,...` -- a scoped user's own counterparties (margin analysts).
- `` (empty) -- sees nothing: an authenticated user with no access rows.

API read endpoints pass the caller's scope explicitly:
`session_factory(info={RLS_SCOPE_KEY: scope})`.

SQL Server sessions are untouched -- RLS is Postgres-only until G9 retires
SQL Server (ground rule 6).
"""

from typing import Any

from sqlalchemy import event, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session, SessionTransaction

from persistence.db.models import UserCounterpartyAccessORM

APP_ROLE = "mm_app"
RLS_SCOPE_KEY = "rls_scope"
FIRM_WIDE = "*"
FIRM_WIDE_ROLES = frozenset({"approver", "manager", "auditor"})


def scope_for(role: str, username: str, session: Session) -> str:
    """The `app.scope` value for an authenticated user. Firm-wide roles see
    every counterparty; any other role sees only its access rows (possibly
    none). `session` must itself be firm-wide scoped to read the access
    table's rows for this user."""
    if role in FIRM_WIDE_ROLES:
        return FIRM_WIDE
    counterparty_ids = session.scalars(
        select(UserCounterpartyAccessORM.counterparty_id)
        .where(UserCounterpartyAccessORM.username == username)
        .order_by(UserCounterpartyAccessORM.counterparty_id)
    ).all()
    return ",".join(counterparty_ids)


def can_see(scope: str, counterparty_id: str) -> bool:
    """The same rule as the database's app_can_see(), for the few reads that
    don't go through a scoped session (e.g. /trace reads the orchestrator's
    checkpointer directly)."""
    return scope == FIRM_WIDE or counterparty_id in scope.split(",")


@event.listens_for(Session, "after_begin")
def _apply_scope(session: Session, transaction: SessionTransaction, connection: Connection) -> Any:
    if connection.dialect.name != "postgresql":
        return
    scope = session.info.get(RLS_SCOPE_KEY, FIRM_WIDE)
    # SET LOCAL / is_local=true: both reset at transaction end, so a pooled
    # connection never carries one caller's scope into the next transaction.
    connection.execute(text(f"SET LOCAL ROLE {APP_ROLE}"))
    connection.execute(text("SELECT set_config('app.scope', :scope, true)"), {"scope": scope})
