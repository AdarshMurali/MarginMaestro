"""rag chunks pgvector

MM-110 (ADR-0011): the RAG store on Postgres, replacing Chroma on the GCP
track. Postgres only -- SQL Server keeps using Chroma.

- `rag_chunks`: one row per document chunk, 768-dim Gemini embedding,
  HNSW index for cosine distance, plus the metadata columns retrieval filters
  on (counterparty_id, doc_type) and a jsonb copy of the full metadata.
- Row-level security: a chunk is visible when it's shared
  (counterparty_id = '') or its counterparty is in the caller's scope, so a
  margin analyst can't retrieve another book's CSA.

Revision ID: d4e1b9c2a7f5
Revises: b7d2f4a8c613
Create Date: 2026-09-30 18:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4e1b9c2a7f5"
down_revision: str | Sequence[str] | None = "b7d2f4a8c613"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VISIBLE = "counterparty_id = '' OR app_can_see(counterparty_id)"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    op.execute("""
        CREATE TABLE rag_chunks (
            id text PRIMARY KEY,
            counterparty_id varchar(20) NOT NULL DEFAULT '',
            doc_type varchar(50) NOT NULL,
            text text NOT NULL,
            metadata jsonb NOT NULL,
            embedding vector(768) NOT NULL
        )
        """)
    op.execute(
        "CREATE INDEX rag_chunks_embedding_hnsw ON rag_chunks "
        "USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute("CREATE INDEX rag_chunks_scope ON rag_chunks (counterparty_id, doc_type)")
    # mm_app gets table privileges via the default privileges set in b7d2f4a8c613;
    # granted explicitly too, in case this runs as a different migrating user.
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON rag_chunks TO mm_app")
    op.execute("ALTER TABLE rag_chunks ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE rag_chunks FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY counterparty_scope ON rag_chunks USING ({VISIBLE}) WITH CHECK ({VISIBLE})"
    )


def downgrade() -> None:
    if _is_postgres():
        op.execute("DROP TABLE IF EXISTS rag_chunks")
