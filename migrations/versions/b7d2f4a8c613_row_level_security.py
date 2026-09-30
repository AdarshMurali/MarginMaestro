"""row level security

MM-106 (ADR-0011). Adds `user_counterparty_access` on both dialects. On
Postgres only, adds row-level security:

- `mm_app` role: what the app runs as (`SET LOCAL ROLE mm_app` per
  transaction, persistence.db.rls). It is not the table owner and has no
  BYPASSRLS, and every protected table has FORCE ROW LEVEL SECURITY, so the
  policies always apply to it.
- `app_can_see(counterparty_id)`: true when the transaction's `app.scope`
  setting is `*` (firm-wide: approver, manager, auditor, system jobs) or
  lists that counterparty (e.g. `CP-1,CP-2` for a margin analyst's book).
  An unset/empty scope sees nothing.
- One policy per counterparty-scoped table, for reads and writes.

SQL Server (AWS / Azure SQL) gets only the access table; its row filtering
is out of scope until G9 retires it (ground rule 6).

Revision ID: b7d2f4a8c613
Revises: a1c4e7f90b21
Create Date: 2026-09-30 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7d2f4a8c613"
down_revision: str | Sequence[str] | None = "a1c4e7f90b21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "mm_app"

# table -> the SQL expression that yields the row's counterparty id
_THREAD_CP = "substring(thread_id from '[^:]*$')"  # thread_id = "<event_id>:<counterparty_id>"
POLICIES = {
    "counterparties": "app_can_see(id)",
    "portfolios": "app_can_see(counterparty_id)",
    "positions": "EXISTS (SELECT 1 FROM portfolios p WHERE p.id = positions.portfolio_id)",
    "ratings": "app_can_see(counterparty_id)",
    "collateral_items": "app_can_see(counterparty_id)",
    "tickets": "app_can_see(counterparty_id)",
    # NULL counterparty_id = system-level audit rows: firm-wide scope only.
    "audit_log": "app_can_see(counterparty_id)",
    "orchestrator_checkpoints": f"app_can_see({_THREAD_CP})",
    "orchestrator_checkpoint_writes": f"app_can_see({_THREAD_CP})",
}


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    op.create_table(
        "user_counterparty_access",
        sa.Column("username", sa.String(length=50), nullable=False),
        sa.Column("counterparty_id", sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(["username"], ["users.username"]),
        sa.ForeignKeyConstraint(["counterparty_id"], ["counterparties.id"]),
        sa.PrimaryKeyConstraint("username", "counterparty_id"),
    )
    if not _is_postgres():
        return

    op.execute(f"""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                CREATE ROLE {APP_ROLE} NOLOGIN;
            END IF;
        END $$
        """)
    # The migrating user must be able to SET ROLE mm_app (it's also the app's
    # login user locally and in CI; in Cloud SQL the IAM app user gets this
    # grant in MM-108).
    op.execute(f"GRANT {APP_ROLE} TO CURRENT_USER")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP_ROLE}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {APP_ROLE}"
    )
    op.execute("""
        CREATE OR REPLACE FUNCTION app_can_see(counterparty text) RETURNS boolean
        LANGUAGE sql STABLE AS $$
            SELECT coalesce(current_setting('app.scope', true), '') = '*'
                OR (counterparty IS NOT NULL AND counterparty = ANY(
                    string_to_array(coalesce(current_setting('app.scope', true), ''), ',')
                ))
        $$
        """)
    op.execute(f"GRANT EXECUTE ON FUNCTION app_can_see(text) TO {APP_ROLE}")

    for table, expression in POLICIES.items():
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY counterparty_scope ON {table} "
            f"USING ({expression}) WITH CHECK ({expression})"
        )


def downgrade() -> None:
    if _is_postgres():
        for table in POLICIES:
            op.execute(f"DROP POLICY IF EXISTS counterparty_scope ON {table}")
            op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
        op.execute("DROP FUNCTION IF EXISTS app_can_see(text)")
        op.execute(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
            f"REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM {APP_ROLE}"
        )
        op.execute(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
            f"REVOKE USAGE, SELECT ON SEQUENCES FROM {APP_ROLE}"
        )
        op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {APP_ROLE}")
        op.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {APP_ROLE}")
        op.execute(f"REVOKE USAGE ON SCHEMA public FROM {APP_ROLE}")
        # The role is cluster-wide and may be shared by other databases on the
        # same server (e.g. a second checkout); leave it in place.
    op.drop_table("user_counterparty_access")
