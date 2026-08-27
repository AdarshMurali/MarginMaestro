from urllib.parse import quote_plus

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from config.settings import Settings, get_settings

ODBC_DRIVER = "ODBC Driver 18 for SQL Server"


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
    return create_engine(build_connection_url(settings or get_settings()), pool_pre_ping=True)


def get_session_factory(settings: Settings | None = None) -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(settings))
