from unittest.mock import MagicMock, patch

import pytest

from persistence.db import grant_app_role as module


def _engine(dialect: str = "postgresql") -> tuple[MagicMock, MagicMock]:
    engine = MagicMock()
    engine.dialect.name = dialect
    engine.dialect.identifier_preparer.quote.side_effect = lambda name: f'"{name}"'
    conn = engine.begin.return_value.__enter__.return_value
    return engine, conn


def test_grants_mm_app_to_each_user_as_a_quoted_identifier():
    engine, conn = _engine()

    module.grant_app_role(engine, ["mm-api-sa@marginmaestro-demo.iam", "mm-agent-sa@x.iam"])

    statements = [str(call.args[0]) for call in conn.execute.call_args_list]
    assert statements == [
        'GRANT mm_app TO "mm-api-sa@marginmaestro-demo.iam"',
        'GRANT mm_app TO "mm-agent-sa@x.iam"',
    ]


def test_requires_at_least_one_user():
    engine, _ = _engine()

    with pytest.raises(ValueError):
        module.grant_app_role(engine, [])


def test_cli_refuses_sql_server():
    engine, _ = _engine("mssql")
    with patch.object(module, "get_engine", return_value=engine), pytest.raises(SystemExit):
        module.main(["someone"])


def test_cli_grants_on_postgres(capsys):
    engine, conn = _engine()
    with patch.object(module, "get_engine", return_value=engine):
        module.main(["mm-api-sa@marginmaestro-demo.iam"])

    assert conn.execute.call_count == 1
    assert "Granted mm_app" in capsys.readouterr().out
