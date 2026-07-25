from config.settings import Settings
from persistence.db.engine import build_connection_url


def test_build_connection_url_encodes_special_characters() -> None:
    settings = Settings(
        _env_file=None,
        db_host="localhost",
        db_port=1433,
        db_name="marginmaestro",
        db_user="sa",
        db_password="Some!Pass@word#1",
    )

    url = build_connection_url(settings)

    assert url.startswith("mssql+pyodbc://sa:")
    assert "@localhost:1433/marginmaestro" in url
    assert "driver=ODBC+Driver+18+for+SQL+Server" in url
    assert "TrustServerCertificate=yes" in url
    # The raw special characters must not appear unencoded in the URL.
    assert "!Pass@word#1" not in url


def test_build_connection_url_handles_missing_credentials() -> None:
    settings = Settings(
        _env_file=None,
        db_host="localhost",
        db_port=1433,
        db_name="marginmaestro",
        db_user=None,
        db_password=None,
    )

    url = build_connection_url(settings)

    assert url.startswith("mssql+pyodbc://:@localhost:1433/marginmaestro")
