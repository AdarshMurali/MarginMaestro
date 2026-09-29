from sqlalchemy import create_engine, text

from config.settings import Settings
from persistence.db.engine import build_connection_url, connect_args, db_dialect


def ensure_database_exists(settings: Settings) -> None:
    """Create the target database if it doesn't exist yet (local dev only).

    Azure SQL Edge (like SQL Server generally) only creates the system
    `master` database on first start -- unlike some other DB images,
    there's no env var that auto-creates a named database. The Postgres
    image does create POSTGRES_DB, but checking here keeps a renamed
    DB_NAME working without recreating the container.
    """
    postgres = db_dialect(settings) == "postgres"
    admin_db = "postgres" if postgres else "master"
    engine = create_engine(
        build_connection_url(settings, database=admin_db),
        isolation_level="AUTOCOMMIT",
        connect_args=connect_args(settings),
    )
    try:
        with engine.connect() as conn:
            if postgres:
                exists = conn.execute(
                    text("SELECT 1 FROM pg_database WHERE datname = :name"),
                    {"name": settings.db_name},
                ).scalar()
                if not exists:
                    # CREATE DATABASE can't take a bind parameter; quote the
                    # identifier with the dialect's own quoting instead.
                    quoted = engine.dialect.identifier_preparer.quote(settings.db_name)
                    conn.execute(text(f"CREATE DATABASE {quoted}"))
            else:
                conn.execute(
                    text("IF DB_ID(:name) IS NULL EXEC('CREATE DATABASE [' + :name + ']')"),
                    {"name": settings.db_name},
                )
    finally:
        engine.dispose()
