"""Seeds the fixed demo login accounts: run once with
`python -m persistence.seed_users`. Idempotent -- re-running just re-hashes
and re-merges the same rows, matching this project's other seed scripts'
style (persistence.batch_loader). `manager` (Phase 9 scope addition) holds
the second signature for elite-tier counterparties' two-person sign-off --
a distinct role from `approver`, not a same-person block on one role, so
one demo user can't satisfy both signatures on the same call."""

import bcrypt

from config.settings import Settings, get_settings
from persistence.db.engine import get_session_factory
from persistence.db.models import UserORM


def _hash(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def seed_demo_users(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    session_factory = get_session_factory(settings)
    with session_factory() as session:
        session.merge(
            UserORM(
                username="approver",
                password_hash=_hash(settings.demo_approver_password),
                role="approver",
            )
        )
        session.merge(
            UserORM(
                username="viewer",
                password_hash=_hash(settings.demo_viewer_password),
                role="viewer",
            )
        )
        session.merge(
            UserORM(
                username="manager",
                password_hash=_hash(settings.demo_manager_password),
                role="manager",
            )
        )
        session.commit()


if __name__ == "__main__":
    seed_demo_users()
    print("Seeded demo users: approver, viewer, manager")
