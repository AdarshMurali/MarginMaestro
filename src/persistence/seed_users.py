"""Seeds the fixed demo login accounts: run once with
`python -m persistence.seed_users`, after `persistence.batch_loader` (the
analysts' access rows reference the seeded counterparties). Idempotent --
re-running just re-hashes and re-merges the same rows, matching this
project's other seed scripts' style (persistence.batch_loader). `manager`
(Phase 9 scope addition) holds the second signature for elite-tier
counterparties' two-person sign-off -- a distinct role from `approver`, not a
same-person block on one role, so one demo user can't satisfy both
signatures on the same call.

MM-106: read-only margin analysts each cover one "book" of counterparties and
see only those (row-level security on Postgres); the auditor sees everything,
read-only. Replaces the old single `viewer` account."""

import bcrypt

from config.settings import Settings, get_settings
from persistence.db.engine import get_session_factory
from persistence.db.models import UserCounterpartyAccessORM, UserORM

# username -> counterparties in that analyst's book
ANALYST_BOOKS: dict[str, list[str]] = {
    "analyst1": ["CP-1", "CP-2", "CP-3", "CP-4"],
    "analyst2": ["CP-5", "CP-6", "CP-7", "CP-8"],
}


def _hash(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def seed_demo_users(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    session_factory = get_session_factory(settings)
    accounts = [
        ("approver", settings.demo_approver_password, "approver"),
        ("manager", settings.demo_manager_password, "manager"),
        ("auditor", settings.demo_auditor_password, "auditor"),
        *[(name, settings.demo_analyst_password, "viewer") for name in ANALYST_BOOKS],
    ]
    with session_factory() as session:
        for username, password, role in accounts:
            session.merge(UserORM(username=username, password_hash=_hash(password), role=role))
        # Flush users first: access rows reference them by foreign key.
        session.flush()
        for username, counterparty_ids in ANALYST_BOOKS.items():
            for counterparty_id in counterparty_ids:
                session.merge(
                    UserCounterpartyAccessORM(username=username, counterparty_id=counterparty_id)
                )
        session.commit()


if __name__ == "__main__":
    seed_demo_users()
    print("Seeded demo users: approver, manager, auditor, analyst1 (CP-1..4), analyst2 (CP-5..8)")
