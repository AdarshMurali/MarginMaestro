"""Lets IAM database users act as `mm_app` (MM-108).

Row-level security runs every app transaction as `SET LOCAL ROLE mm_app`
(persistence.db.rls). Locally and in CI the login user already holds that
role (the migration grants it to whoever runs it). In Cloud SQL the runtime
service accounts log in as separate IAM database users, so they need the
grant too -- run once after `alembic upgrade head`, as the migration user:

    python -m persistence.db.grant_app_role \\
        mm-api-sa@marginmaestro-demo.iam mm-agent-sa@marginmaestro-demo.iam ...

(names from `terraform -chdir=infra/gcp output cloudsql_runtime_db_users`).
Idempotent: granting an existing membership is a no-op in Postgres.
"""

import sys

from sqlalchemy import Engine, text

from persistence.db.engine import get_engine
from persistence.db.rls import APP_ROLE


def grant_app_role(engine: Engine, usernames: list[str]) -> None:
    if not usernames:
        raise ValueError("Give at least one database username to grant mm_app to")
    quote = engine.dialect.identifier_preparer.quote
    with engine.begin() as conn:
        for username in usernames:
            # Role/user names can't be bind parameters; quote them as identifiers.
            conn.execute(text(f"GRANT {APP_ROLE} TO {quote(username)}"))


def main(argv: list[str]) -> None:
    engine = get_engine()
    if engine.dialect.name != "postgresql":
        raise SystemExit("grant_app_role is Postgres-only (set DB_DIALECT=postgres)")
    grant_app_role(engine, argv)
    print(f"Granted {APP_ROLE} to: {', '.join(argv)}")


if __name__ == "__main__":
    main(sys.argv[1:])
