"""append-only audit log

MM-137 (ADR-0015): the application audit trail is append-only, enforced by
database grants and not just by convention. On Postgres, the app role
`mm_app` (what every app transaction runs as, persistence.db.rls) loses
UPDATE and DELETE on `audit_log`: it can still insert and read (under
row-level security), but no app code path -- or SQL injected into one -- can
rewrite or erase history. TRUNCATE was never granted.

The table owner (the migration login) keeps its rights, so a deliberate,
audited maintenance task is still possible outside the app.

SQL Server (AWS / Azure SQL) is untouched, like the RLS migration: grants
there are out of scope until G9 retires it (ground rule 6).

Revision ID: e3f8a1c5d927
Revises: d4e1b9c2a7f5
Create Date: 2026-10-05 22:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e3f8a1c5d927"
down_revision: str | Sequence[str] | None = "d4e1b9c2a7f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "mm_app"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM {APP_ROLE}")


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute(f"GRANT UPDATE, DELETE ON audit_log TO {APP_ROLE}")
