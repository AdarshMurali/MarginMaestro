from urllib.parse import quote_plus

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from config.settings import Settings, get_settings

ODBC_DRIVER = "ODBC Driver 18 for SQL Server"

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


def build_connection_url(settings: Settings) -> str:
    user = quote_plus(settings.db_user or "")
    password = quote_plus(settings.db_password or "")
    driver = quote_plus(ODBC_DRIVER)
    return (
        f"mssql+pyodbc://{user}:{password}@{settings.db_host}:{settings.db_port}"
        f"/{settings.db_name}?driver={driver}&TrustServerCertificate=yes"
    )


def get_engine(settings: Settings | None = None) -> Engine:
    # pool_pre_ping: without it, a connection Azure SQL has silently dropped
    # (idle timeout, network blip) sits in the pool looking valid until the
    # next checkout, then fails on the caller's first query with a raw TCP
    # error instead of SQLAlchemy transparently replacing it. Found live
    # both during MM-70's local verification (a stale connection after the
    # dev container sat idle) and again running MM-102's first deployed
    # queries against Azure SQL for real.
    return create_engine(
        build_connection_url(settings or get_settings()),
        pool_pre_ping=True,
        connect_args={"timeout": AZURE_SERVERLESS_RESUME_TIMEOUT_SECONDS},
    )


def get_session_factory(settings: Settings | None = None) -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(settings))
