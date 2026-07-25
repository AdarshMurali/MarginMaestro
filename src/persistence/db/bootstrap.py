from urllib.parse import quote_plus

from sqlalchemy import create_engine, text

from config.settings import Settings
from persistence.db.engine import ODBC_DRIVER


def ensure_database_exists(settings: Settings) -> None:
    """Create the target database if it doesn't exist yet.

    Azure SQL Edge (like SQL Server generally) only creates the system
    `master` database on first start -- unlike some other DB images,
    there's no env var that auto-creates a named database.
    """
    user = quote_plus(settings.db_user or "")
    password = quote_plus(settings.db_password or "")
    driver = quote_plus(ODBC_DRIVER)
    master_url = (
        f"mssql+pyodbc://{user}:{password}@{settings.db_host}:{settings.db_port}"
        f"/master?driver={driver}&TrustServerCertificate=yes"
    )
    engine = create_engine(master_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(
                text("IF DB_ID(:name) IS NULL EXEC('CREATE DATABASE [' + :name + ']')"),
                {"name": settings.db_name},
            )
    finally:
        engine.dispose()
