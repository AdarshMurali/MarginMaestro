"""desk chat jobs

MM-147 follow-up: async "Ask the Desk" turns. POST /desk/chat used to block
on Agent Runtime's call directly -- found live, it can take 90+ seconds on a
cold start, past Firebase Hosting's edge proxy timeout to the frontend (the
backend call itself succeeded every time; the browser just never saw the
answer). Now the endpoint creates a row here and returns its id immediately;
the actual Agent Runtime call runs via Cloud Tasks or inline depending on
DESK_JOB_DISPATCH, and the frontend polls GET /desk/chat/{job_id} until
status is no longer "pending".

No row-level security: a job is scoped by username (checked in the API, see
api.main._desk_job_response -- 404 for a job that isn't the caller's own),
not by counterparty, so the counterparty-scoped RLS policy pattern used
elsewhere (migration b7d2f4a8c613) doesn't apply here.

Revision ID: a7c3e9f1b204
Revises: f2a9c4e7b318
Create Date: 2026-10-16 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7c3e9f1b204"
down_revision: str | Sequence[str] | None = "f2a9c4e7b318"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "mm_app"
TABLE = "desk_chat_jobs"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("username", sa.String(length=100), nullable=False),
        sa.Column("message", sa.String(length=2000), nullable=False),
        sa.Column("session_id", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("tools_used", sa.JSON(), nullable=True),
        sa.Column("error_detail", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    if not _is_postgres():
        return
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {TABLE} TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_table(TABLE)
