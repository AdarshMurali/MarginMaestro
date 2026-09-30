from unittest.mock import MagicMock, patch

import pytest

from config.settings import Settings
from persistence.db import bootstrap
from persistence.db.engine import build_connection_url, connect_args, db_dialect, get_engine


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


# --- MM-104: DB_DIALECT=mssql|postgres ---------------------------------------


def _pg(**overrides) -> Settings:
    values = {
        "db_dialect": "postgres",
        "db_host": "localhost",
        "db_port": 5432,
        "db_name": "marginmaestro",
        "db_user": "marginmaestro",
        "db_password": "p@ss/word",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_default_dialect_is_mssql_so_aws_is_unchanged() -> None:
    assert db_dialect(Settings(_env_file=None)) == "mssql"


def test_postgres_url_uses_psycopg_and_encodes_credentials() -> None:
    url = build_connection_url(_pg())

    assert url == "postgresql+psycopg://marginmaestro:p%40ss%2Fword@localhost:5432/marginmaestro"


def test_url_can_target_another_database_for_bootstrap() -> None:
    assert build_connection_url(_pg(), database="postgres").endswith(":5432/postgres")
    assert "/master?driver=" in build_connection_url(Settings(_env_file=None), database="master")


def test_dialect_is_case_and_space_insensitive() -> None:
    assert db_dialect(_pg(db_dialect=" Postgres ")) == "postgres"


def test_unknown_dialect_fails_loud() -> None:
    with pytest.raises(ValueError, match="DB_DIALECT"):
        build_connection_url(_pg(db_dialect="oracle"))


def test_connect_args_per_dialect() -> None:
    assert connect_args(_pg()) == {"connect_timeout": 10}
    assert connect_args(Settings(_env_file=None)) == {"timeout": 60}


def test_get_engine_passes_dialect_specific_connect_args() -> None:
    with patch("persistence.db.engine.create_engine") as create:
        get_engine(_pg())

    assert create.call_args.args[0].startswith("postgresql+psycopg://")
    assert create.call_args.kwargs == {
        "pool_pre_ping": True,
        "connect_args": {"connect_timeout": 10},
    }


def _fake_engine(existing: bool):
    engine = MagicMock()
    conn = engine.connect.return_value.__enter__.return_value
    conn.execute.return_value.scalar.return_value = 1 if existing else None
    engine.dialect.identifier_preparer.quote.side_effect = lambda name: f'"{name}"'
    return engine, conn


def _sql(call) -> str:
    return str(call.args[0])


def test_postgres_bootstrap_creates_missing_database_via_admin_db() -> None:
    engine, conn = _fake_engine(existing=False)
    with patch.object(bootstrap, "create_engine", return_value=engine) as create:
        bootstrap.ensure_database_exists(_pg())

    assert create.call_args.args[0].endswith(":5432/postgres")
    assert create.call_args.kwargs["isolation_level"] == "AUTOCOMMIT"
    statements = [_sql(c) for c in conn.execute.call_args_list]
    assert statements == [
        "SELECT 1 FROM pg_database WHERE datname = :name",
        'CREATE DATABASE "marginmaestro"',
    ]
    engine.dispose.assert_called_once()


def test_postgres_bootstrap_skips_existing_database() -> None:
    engine, conn = _fake_engine(existing=True)
    with patch.object(bootstrap, "create_engine", return_value=engine):
        bootstrap.ensure_database_exists(_pg())

    assert [_sql(c) for c in conn.execute.call_args_list] == [
        "SELECT 1 FROM pg_database WHERE datname = :name"
    ]


def test_mssql_bootstrap_unchanged() -> None:
    engine, conn = _fake_engine(existing=False)
    settings = Settings(_env_file=None, db_host="localhost", db_user="sa", db_password="x")
    with patch.object(bootstrap, "create_engine", return_value=engine) as create:
        bootstrap.ensure_database_exists(settings)

    assert "/master?driver=" in create.call_args.args[0]
    assert create.call_args.kwargs["connect_args"] == {"timeout": 60}
    assert "IF DB_ID(:name) IS NULL" in _sql(conn.execute.call_args_list[0])
