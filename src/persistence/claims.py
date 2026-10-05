"""Exactly-once claims on `processed_events` (G6, MM-133/MM-134).

The same pattern the impact consumer uses for runs (MM-121): insert a row
whose primary key names the work; a duplicate (a webhook redelivered by Meta,
a replayed graph node) fails the insert and is skipped. Keys longer than the
column are hashed, keeping a readable prefix."""

import hashlib
from datetime import UTC, datetime

from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from persistence.db.models import ProcessedEventORM

MAX_KEY_CHARS = 200


def claim_key(key: str) -> str:
    if len(key) <= MAX_KEY_CHARS:
        return key
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return f"{key[: MAX_KEY_CHARS - len(digest) - 1]}#{digest}"


def claim_once(session_factory: sessionmaker[Session], key: str) -> bool:
    """True if this caller now owns `key`; False if it was already claimed."""
    with session_factory() as session:
        session.add(ProcessedEventORM(event_id=claim_key(key), processed_at=datetime.now(UTC)))
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            return False
    return True


def release_claim(session_factory: sessionmaker[Session], key: str) -> None:
    """Undo a claim so the work can be retried (only after an unexpected failure)."""
    with session_factory() as session:
        session.execute(
            delete(ProcessedEventORM).where(ProcessedEventORM.event_id == claim_key(key))
        )
        session.commit()
