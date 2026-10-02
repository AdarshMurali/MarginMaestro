"""MM-123: Cloud SQL IAM database login (token as password) and the
connection URLs for Unix sockets."""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from config.settings import Settings
from persistence.db.engine import build_connection_url, db_auth, get_engine
from persistence.db.iam_auth import SQL_LOGIN_SCOPE, IamTokenProvider, use_iam_login

SOCKET = "/cloudsql/marginmaestro-demo:us-central1:marginmaestro-pg"
IAM_USER = "mm-api-sa@marginmaestro-demo.iam"


def _settings(**overrides) -> Settings:
    values = {"db_dialect": "postgres", "db_port": 5432, "db_user": IAM_USER} | overrides
    return Settings(_env_file=None, **values)


def test_iam_url_over_the_cloud_run_socket_has_no_password():
    url = make_url(build_connection_url(_settings(db_auth="iam", db_host=SOCKET)))

    assert (url.username, url.password, url.host) == (IAM_USER, None, None)
    assert url.query == {"host": SOCKET, "port": "5432"}
    assert url.database == "marginmaestro"


def test_iam_url_over_tcp_for_the_local_proxy():
    url = make_url(build_connection_url(_settings(db_auth="iam", db_host="127.0.0.1")))

    assert (url.username, url.password, url.host, url.port) == (IAM_USER, None, "127.0.0.1", 5432)


def test_password_login_is_unchanged():
    url = make_url(
        build_connection_url(_settings(db_user="postgres", db_password="p@ss", db_host="127.0.0.1"))
    )

    assert (url.username, url.password, url.host) == ("postgres", "p@ss", "127.0.0.1")


def test_password_login_over_a_socket():
    url = make_url(build_connection_url(_settings(db_password="pw", db_host=SOCKET)))

    assert url.password == "pw"
    assert url.query["host"] == SOCKET


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"db_auth": "kerberos"}, "DB_AUTH must be one of"),
        ({"db_auth": "iam", "db_dialect": "mssql"}, "needs DB_DIALECT=postgres"),
    ],
)
def test_bad_auth_settings_fail_loud(overrides, message):
    with pytest.raises(ValueError, match=message):
        db_auth(_settings(**overrides))


def test_each_new_connection_gets_a_token_as_its_password():
    engine = create_engine(build_connection_url(_settings(db_auth="iam", db_host=SOCKET)))
    provider = MagicMock()
    provider.token.side_effect = ["token-1", "token-2"]
    use_iam_login(engine, provider)

    first, second = {"user": IAM_USER}, {"user": IAM_USER}
    engine.dialect.dispatch.do_connect(engine.dialect, None, [], first)
    engine.dialect.dispatch.do_connect(engine.dialect, None, [], second)

    assert (first["password"], second["password"]) == ("token-1", "token-2")


def test_get_engine_wires_iam_login_only_when_asked():
    with patch("persistence.db.engine.use_iam_login") as wire:
        get_engine(_settings(db_auth="iam", db_host=SOCKET))
        get_engine(_settings(db_password="pw", db_host="127.0.0.1"))

    wire.assert_called_once()


def test_token_provider_refreshes_only_when_the_token_is_stale():
    credentials = MagicMock(valid=False, token="fresh")

    def refresh(_request):
        credentials.valid = True

    credentials.refresh.side_effect = refresh
    provider = IamTokenProvider(credentials)

    assert provider.token() == "fresh"
    assert provider.token() == "fresh"
    credentials.refresh.assert_called_once()


def test_token_provider_uses_default_credentials_with_the_sql_login_scope():
    credentials = MagicMock(valid=True, token="t")
    with patch("google.auth.default", return_value=(credentials, "proj")) as default:
        assert IamTokenProvider().token() == "t"

    assert default.call_args.kwargs == {"scopes": [SQL_LOGIN_SCOPE]}
