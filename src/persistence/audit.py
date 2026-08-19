"""Immutable audit trail (MM-91, Phase 9, docs/AGENTS.md's "Audit
(cross-cutting)"): every real lifecycle step of a margin-call run gets one
insert-only row here -- never updated, never deleted. Deliberately
independent of LangGraph's own checkpoint history (api/margin_call_trace.py,
MM-54): AzureSQLSaver can silently drop a checkpoint row under concurrent
writes (see docs/PROGRESS.md's tech-debt notes), so a genuinely reliable
audit record needs its own plain-SQL, non-LangGraph-managed write path.

A single run is identified by (correlation_id, counterparty_id) together,
not correlation_id alone -- api/simulate.py's fan-out deliberately gives
every counterparty affected by one triggering event the same
correlation_id (grouping everything one event caused), matching the pair
every structlog call in agents/orchestrator.py already binds together.
Found live while verifying this module's own read endpoint, which
initially queried by correlation_id alone and returned other
counterparties' events mixed in. counterparty_id is nullable for
non-run-scoped audit events (e.g. persistence.batch_loader's "batch_load"
entry, which isn't about any one counterparty)."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from persistence.db.models import AuditLogORM


def record_audit_event(
    session: Session,
    correlation_id: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
    counterparty_id: str | None = None,
) -> None:
    """Appends one audit_log row. `payload` must already be JSON-safe (e.g.
    via a Pydantic model's `.model_dump(mode="json")`) -- the column is a
    plain JSON type, not a Python-object store."""
    session.add(
        AuditLogORM(
            correlation_id=correlation_id,
            counterparty_id=counterparty_id,
            event_type=event_type,
            payload=payload,
            created_at=datetime.now(UTC),
        )
    )
    session.commit()


def list_audit_events(
    session: Session, correlation_id: str, counterparty_id: str
) -> list[AuditLogORM]:
    """Every audit event for one specific run, oldest first -- the full
    lifecycle in the order it actually happened. Requires both
    correlation_id and counterparty_id (see this module's docstring for
    why correlation_id alone isn't enough to identify one run)."""
    return list(
        session.execute(
            select(AuditLogORM)
            .where(
                AuditLogORM.correlation_id == correlation_id,
                AuditLogORM.counterparty_id == counterparty_id,
            )
            .order_by(AuditLogORM.id.asc())
        )
        .scalars()
        .all()
    )
