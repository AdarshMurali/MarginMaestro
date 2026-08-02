"""Seeds the 2 fixed demo login accounts (MM-57): run once with
`python -m persistence.seed_users`. Idempotent -- re-running just re-hashes
and re-merges the same two rows, matching this project's other seed
scripts' style (persistence.batch_loader)."""

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
        session.commit()


if __name__ == "__main__":
    seed_demo_users()
    print("Seeded demo users: approver, viewer")
