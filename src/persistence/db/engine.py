from typing import Any
from urllib.parse import quote_plus

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

import persistence.db.rls  # noqa: F401  -- registers the RLS session listener (MM-106)
from config.settings import Settings, get_settings
from persistence.db.iam_auth import use_iam_login

ODBC_DRIVER = "ODBC Driver 18 for SQL Server"

# MM-104 (ground rule 6): SQL Server stays the default so the AWS deployment
# (Azure SQL) is unchanged; Postgres is opted into for local GCP work, CI and
# Cloud SQL.
DIALECTS = ("mssql", "postgres")

# The deployed database (finsight-sql-server, GP_S_Gen5 Serverless) auto-
# pauses after an hour of no activity to keep cost near-zero when nobody's
# using the app -- the right behavior for a mostly-idle demo, not a bug.
# But the *first* connection after a pause has to wait for Azure to resume
# it first, which can take up to ~30s; pyodbc's default login timeout is
# shorter than that, so a cold-start connection fails with a genuine
# 'Login timeout expired' (HYT00) that looks identical to a real outage.
# Found live, repeatedly, throughout MM-102/103's deployment session before
# the real cause (auto-pause, not flakiness) was identified. Raising the
# login timeout is pyodbc/Microsoft's own documented fix for this -- no
# retry loop needed, one longer wait comfortably covers the resume window.
AZURE_SERVERLESS_RESUME_TIMEOUT_SECONDS = 60

POSTGRES_CONNECT_TIMEOUT_SECONDS = 10


def db_dialect(settings: Settings) -> str:
    dialect = settings.db_dialect.strip().lower()
    if dialect not in DIALECTS:
        raise ValueError(f"DB_DIALECT must be one of {DIALECTS}, got {settings.db_dialect!r}")
    return dialect


DB_AUTH_MODES = ("password", "iam")


def db_auth(settings: Settings) -> str:
    mode = settings.db_auth.strip().lower()
    if mode not in DB_AUTH_MODES:
        raise ValueError(f"DB_AUTH must be one of {DB_AUTH_MODES}, got {settings.db_auth!r}")
    if mode == "iam" and db_dialect(settings) != "postgres":
        raise ValueError("DB_AUTH=iam needs DB_DIALECT=postgres (Cloud SQL)")
    return mode


def build_connection_url(settings: Settings, database: str | None = None) -> str:
    user = quote_plus(settings.db_user or "")
    password = quote_plus(settings.db_password or "")
    name = database or settings.db_name
    if db_dialect(settings) == "postgres":
        # IAM login: no password in the URL on purpose -- a short-lived OAuth
        # token is set as the password on every new connection (iam_auth,
        # do_connect), so the database is still password-protected.
        credentials = user if db_auth(settings) == "iam" else f"{user}:{password}"
        host = settings.db_host or ""
        if host.startswith("/"):  # Unix socket directory (Cloud Run's /cloudsql/...)
            return (
                f"postgresql+psycopg://{credentials}@/{name}"  # NOSONAR -- IAM token password
                f"?host={quote_plus(host)}&port={settings.db_port}"
            )
        return f"postgresql+psycopg://{credentials}@{host}:{settings.db_port}/{name}"  # NOSONAR
    driver = quote_plus(ODBC_DRIVER)
    return (
        f"mssql+pyodbc://{user}:{password}@{settings.db_host}:{settings.db_port}"
        f"/{name}?driver={driver}&TrustServerCertificate=yes"
    )


def connect_args(settings: Settings) -> dict[str, Any]:
    if db_dialect(settings) == "postgres":
        return {"connect_timeout": POSTGRES_CONNECT_TIMEOUT_SECONDS}
    return {"timeout": AZURE_SERVERLESS_RESUME_TIMEOUT_SECONDS}


def get_engine(settings: Settings | None = None) -> Engine:
    settings = settings or get_settings()
    # pool_pre_ping: without it, a connection Azure SQL has silently dropped
    # (idle timeout, network blip) sits in the pool looking valid until the
    # next checkout, then fails on the caller's first query with a raw TCP
    # error instead of SQLAlchemy transparently replacing it. Found live
    # both during MM-70's local verification (a stale connection after the
    # dev container sat idle) and again running MM-102's first deployed
    # queries against Azure SQL for real.
    engine = create_engine(  # NOSONAR -- DB_AUTH=iam sets a token password per connection
        build_connection_url(settings),
        pool_pre_ping=True,
        connect_args=connect_args(settings),
    )
    if db_auth(settings) == "iam":
        use_iam_login(engine)
    return engine


def get_session_factory(settings: Settings | None = None) -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(settings))
