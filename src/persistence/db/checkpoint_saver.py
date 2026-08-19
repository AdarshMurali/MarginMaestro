"""Persisted LangGraph checkpointer (MM-38) backed by this project's own SQL
database (persistence.db.engine), so an orchestrator run paused at
await_approval survives a process restart -- no official LangGraph
checkpoint backend exists for SQL Server (only Postgres/SQLite/MongoDB), so
this implements the BaseCheckpointSaver contract directly.

Stores the full Checkpoint dict (including channel_values) as one row per
step rather than LangGraph's own Postgres/SQLite savers' per-channel
blob-dedup scheme -- this orchestrator's graph is small/linear (a handful of
steps per run) and doesn't need cross-checkpoint blob sharing. Sync-only:
this project's orchestrator entry points (start_run/resume_run) are
synchronous, so the async methods are left unimplemented (base class
default raises NotImplementedError).

Guarded by a single instance-wide lock: LangGraph's Pregel runtime executes
via an internal ThreadPoolExecutor and calls checkpointer methods
concurrently even for a simple sequential graph -- found via a real,
intermittent (roughly 1-in-5 to 1-in-8 runs) failure where a concurrent
put()/put_writes() pair against the same SQLite connection silently lost a
checkpoint row. Serializing here is simplest and correct; a real SQL Server
backend would tolerate the concurrency better (separate pooled connections,
row-level locking) but the lock costs nothing at this project's scale and
removes the race entirely rather than relying on backend-specific luck."""

import threading
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    get_checkpoint_id,
    get_checkpoint_metadata,
)
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from persistence.db.models import CheckpointORM, CheckpointWriteORM


class AzureSQLSaver(BaseCheckpointSaver[int]):
    def __init__(
        self, session_factory: sessionmaker[Session], lock: "threading.Lock | None" = None
    ) -> None:
        """`lock` is injectable so a caller that also writes to the same
        underlying connection from outside this class (e.g. the
        orchestrator's audit-log writes, MM-91) can share this exact lock
        rather than merely avoiding races against this class's own
        put()/put_writes() calls -- see this module's docstring for why any
        concurrent write against a single shared connection is a real risk,
        not just a theoretical one. Defaults to a private lock when not
        given, matching this class's original (pre-MM-91) behavior."""
        super().__init__()
        self._session_factory = session_factory
        self._lock = lock or threading.Lock()

    def _pending_writes(
        self, session: Session, thread_id: str, checkpoint_ns: str, checkpoint_id: str
    ) -> list[tuple[str, str, Any]]:
        rows = (
            session.execute(
                select(CheckpointWriteORM)
                .where(
                    CheckpointWriteORM.thread_id == thread_id,
                    CheckpointWriteORM.checkpoint_ns == checkpoint_ns,
                    CheckpointWriteORM.checkpoint_id == checkpoint_id,
                )
                .order_by(CheckpointWriteORM.task_id, CheckpointWriteORM.idx)
            )
            .scalars()
            .all()
        )
        return [
            (row.task_id, row.channel, self.serde.loads_typed((row.write_type, row.write_blob)))
            for row in rows
        ]

    def _to_tuple(self, session: Session, row: CheckpointORM) -> CheckpointTuple:
        checkpoint: Checkpoint = self.serde.loads_typed((row.checkpoint_type, row.checkpoint_blob))
        metadata: CheckpointMetadata = self.serde.loads_typed(
            (row.metadata_type, row.metadata_blob)
        )
        parent_config: RunnableConfig | None = (
            {
                "configurable": {
                    "thread_id": row.thread_id,
                    "checkpoint_ns": row.checkpoint_ns,
                    "checkpoint_id": row.parent_checkpoint_id,
                }
            }
            if row.parent_checkpoint_id
            else None
        )
        return CheckpointTuple(
            config={
                "configurable": {
                    "thread_id": row.thread_id,
                    "checkpoint_ns": row.checkpoint_ns,
                    "checkpoint_id": row.checkpoint_id,
                }
            },
            checkpoint=checkpoint,
            metadata=metadata,
            parent_config=parent_config,
            pending_writes=self._pending_writes(
                session, row.thread_id, row.checkpoint_ns, row.checkpoint_id
            ),
        )

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        with self._lock, self._session_factory() as session:
            if checkpoint_id := get_checkpoint_id(config):
                row = session.get(CheckpointORM, (thread_id, checkpoint_ns, checkpoint_id))
            else:
                row = session.execute(
                    select(CheckpointORM)
                    .where(
                        CheckpointORM.thread_id == thread_id,
                        CheckpointORM.checkpoint_ns == checkpoint_ns,
                    )
                    .order_by(CheckpointORM.checkpoint_id.desc())
                    .limit(1)
                ).scalar_one_or_none()
            return self._to_tuple(session, row) if row is not None else None

    def list(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:
        # Materialized eagerly under the lock, then yielded from a plain list
        # afterward -- a bare `yield` here would hold the lock open for the
        # generator's whole lifetime (only released once fully consumed,
        # closed, or GC'd), which can stall other threads if a caller (e.g.
        # one that only wants the first N results) never exhausts it.
        results: list[CheckpointTuple] = []
        with self._lock, self._session_factory() as session:
            stmt = select(CheckpointORM)
            if config is not None:
                stmt = stmt.where(CheckpointORM.thread_id == config["configurable"]["thread_id"])
                checkpoint_ns = config["configurable"].get("checkpoint_ns")
                if checkpoint_ns is not None:
                    stmt = stmt.where(CheckpointORM.checkpoint_ns == checkpoint_ns)
                if checkpoint_id := get_checkpoint_id(config):
                    stmt = stmt.where(CheckpointORM.checkpoint_id == checkpoint_id)
            if before is not None and (before_id := get_checkpoint_id(before)):
                stmt = stmt.where(CheckpointORM.checkpoint_id < before_id)
            stmt = stmt.order_by(CheckpointORM.checkpoint_id.desc())

            for row in session.execute(stmt).scalars().all():
                if limit is not None and len(results) >= limit:
                    break
                tup = self._to_tuple(session, row)
                if filter and not all(tup.metadata.get(k) == v for k, v in filter.items()):
                    continue
                results.append(tup)
        yield from results

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_type, checkpoint_blob = self.serde.dumps_typed(checkpoint)
        metadata_type, metadata_blob = self.serde.dumps_typed(
            get_checkpoint_metadata(config, metadata)
        )
        with self._lock, self._session_factory() as session:
            session.merge(
                CheckpointORM(
                    thread_id=thread_id,
                    checkpoint_ns=checkpoint_ns,
                    checkpoint_id=checkpoint["id"],
                    parent_checkpoint_id=config["configurable"].get("checkpoint_id"),
                    checkpoint_type=checkpoint_type,
                    checkpoint_blob=checkpoint_blob,
                    metadata_type=metadata_type,
                    metadata_blob=metadata_blob,
                    created_at=datetime.now(UTC),
                )
            )
            session.commit()
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint["id"],
            }
        }

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = config["configurable"]["checkpoint_id"]
        with self._lock, self._session_factory() as session:
            existing = {
                (row.task_id, row.idx)
                for row in session.execute(
                    select(CheckpointWriteORM.task_id, CheckpointWriteORM.idx).where(
                        CheckpointWriteORM.thread_id == thread_id,
                        CheckpointWriteORM.checkpoint_ns == checkpoint_ns,
                        CheckpointWriteORM.checkpoint_id == checkpoint_id,
                    )
                )
            }
            for idx, (channel, value) in enumerate(writes):
                write_idx = WRITES_IDX_MAP.get(channel, idx)
                # Regular writes (idx >= 0) are first-write-wins, matching
                # InMemorySaver: a retried task shouldn't clobber the write
                # already recorded for this (task_id, idx) slot. Sentinel
                # channels (negative idx, e.g. ERROR/INTERRUPT) always
                # overwrite -- last write wins.
                if write_idx >= 0 and (task_id, write_idx) in existing:
                    continue
                write_type, write_blob = self.serde.dumps_typed(value)
                session.merge(
                    CheckpointWriteORM(
                        thread_id=thread_id,
                        checkpoint_ns=checkpoint_ns,
                        checkpoint_id=checkpoint_id,
                        task_id=task_id,
                        idx=write_idx,
                        channel=channel,
                        write_type=write_type,
                        write_blob=write_blob,
                        task_path=task_path,
                    )
                )
            session.commit()

    def delete_thread(self, thread_id: str) -> None:
        with self._lock, self._session_factory() as session:
            session.execute(
                delete(CheckpointWriteORM).where(CheckpointWriteORM.thread_id == thread_id)
            )
            session.execute(delete(CheckpointORM).where(CheckpointORM.thread_id == thread_id))
            session.commit()
