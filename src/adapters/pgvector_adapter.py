"""`VectorStore` over Postgres + pgvector (MM-110, ADR-0011). Replaces Chroma
on the GCP track: vectors live in the same database as everything else, and
row-level security applies to retrieval too (an analyst can't retrieve
another book's CSA; shared documents stay visible to everyone).

Table `rag_chunks` is created by migration d4e1b9c2a7f5 (Postgres only):
    id text PK, counterparty_id text ('' = shared), doc_type text,
    text text, metadata jsonb, embedding vector(768) + HNSW (cosine).
Distance is cosine distance (0 = identical); results are nearest first.
"""

from collections.abc import Sequence

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, MetaData, String, Table, Text, or_, select
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.orm import Session, sessionmaker

from ports.vector_store import VectorHit

EMBEDDING_DIMENSIONS = 768


def rag_table(name: str = "rag_chunks", dimensions: int = EMBEDDING_DIMENSIONS) -> Table:
    # Own MetaData, deliberately not the ORM Base: the table exists only on
    # Postgres, and Base.metadata.create_all also runs against SQL Server.
    return Table(
        name,
        MetaData(),
        Column("id", String, primary_key=True),
        Column("counterparty_id", String(20), nullable=False),
        Column("doc_type", String(50), nullable=False),
        Column("text", Text, nullable=False),
        Column("metadata", JSONB, nullable=False),
        Column("embedding", Vector(dimensions), nullable=False),
    )


class PgVectorStore:
    def __init__(self, session_factory: sessionmaker[Session], table: Table | None = None) -> None:
        self._session_factory = session_factory
        self._table = table if table is not None else rag_table()

    def upsert(
        self,
        ids: list[str],
        embeddings: list[Sequence[float]],
        documents: list[str],
        metadatas: list[dict[str, str]],
    ) -> None:
        rows = [
            {
                "id": id_,
                "counterparty_id": metadata.get("counterparty_id", ""),
                "doc_type": metadata.get("doc_type", ""),
                "text": document,
                "metadata": metadata,
                "embedding": list(embedding),
            }
            for id_, embedding, document, metadata in zip(
                ids, embeddings, documents, metadatas, strict=True
            )
        ]
        if not rows:
            return
        statement = insert(self._table).values(rows)
        statement = statement.on_conflict_do_update(
            index_elements=["id"],
            set_={
                c: statement.excluded[c]
                for c in ("counterparty_id", "doc_type", "text", "metadata", "embedding")
            },
        )
        with self._session_factory() as session:
            session.execute(statement)
            session.commit()

    def query(
        self,
        embedding: Sequence[float],
        top_k: int,
        counterparty_id: str | None = None,
        doc_type: str | None = None,
    ) -> list[VectorHit]:
        t = self._table
        distance = t.c.embedding.cosine_distance(list(embedding)).label("distance")
        statement = select(t.c.text, t.c.metadata, distance)
        if counterparty_id:
            statement = statement.where(
                or_(t.c.counterparty_id == counterparty_id, t.c.counterparty_id == "")
            )
        if doc_type:
            statement = statement.where(t.c.doc_type == doc_type)
        statement = statement.order_by(distance).limit(top_k)
        with self._session_factory() as session:
            rows = session.execute(statement).all()
        return [
            VectorHit(text=row.text, metadata=dict(row.metadata), distance=float(row.distance))
            for row in rows
        ]
