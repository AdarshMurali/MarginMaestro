"""postgres vector extension

Enables pgvector on Postgres (local container, CI, Cloud SQL) for the RAG
store that replaces Chroma in G2 (ADR-0011). No-op on SQL Server, so the
same migration chain stays valid on both dialects (MM-104, ground rule 6).

Revision ID: a1c4e7f90b21
Revises: 914af690c86a
Create Date: 2026-09-29 16:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1c4e7f90b21"
down_revision: str | Sequence[str] | None = "914af690c86a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if _is_postgres():
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    if _is_postgres():
        op.execute("DROP EXTENSION IF EXISTS vector")
