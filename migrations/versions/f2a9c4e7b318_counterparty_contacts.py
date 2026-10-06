"""counterparty contacts

MM-143 (ADR-0016 amendment, 2026-10-06): per-counterparty WhatsApp contacts.
A margin-call notice goes to the counterparty's active contact; a
counterparty without one falls back to the WHATSAPP_RECIPIENT default.

- `counterparty_contacts`: one row per (counterparty, channel), written only
  by the admin CLI (`python -m persistence.contacts`). `phone_e164` is
  confidential personal data (data catalog: `llm: deny`).
- Both dialects get the table. On Postgres only, row-level security like the
  other counterparty-scoped tables (migration b7d2f4a8c613): a contact is
  visible to a session whose `app.scope` covers its counterparty, and to
  firm-wide sessions (internal jobs, the CLI, approvers).

Revision ID: f2a9c4e7b318
Revises: e3f8a1c5d927
Create Date: 2026-10-06 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f2a9c4e7b318"
down_revision: str | Sequence[str] | None = "e3f8a1c5d927"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "mm_app"
TABLE = "counterparty_contacts"
VISIBLE = "app_can_see(counterparty_id)"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("counterparty_id", sa.String(length=20), nullable=False),
        sa.Column("contact_name", sa.String(length=200), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("phone_e164", sa.String(length=16), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["counterparty_id"], ["counterparties.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("counterparty_id", "channel"),
    )
    if not _is_postgres():
        return
    # mm_app gets table privileges via the default privileges set in
    # b7d2f4a8c613; granted explicitly too, in case this runs as a different
    # migrating user (as in d4e1b9c2a7f5).
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {TABLE} TO {APP_ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON SEQUENCE {TABLE}_id_seq TO {APP_ROLE}")
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY counterparty_scope ON {TABLE} USING ({VISIBLE}) WITH CHECK ({VISIBLE})"
    )


def downgrade() -> None:
    if _is_postgres():
        op.execute(f"DROP POLICY IF EXISTS counterparty_scope ON {TABLE}")
    op.drop_table(TABLE)
