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
    return create_engine(build_connection_url(settings or get_settings()))


def get_session_factory(settings: Settings | None = None) -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(settings))
