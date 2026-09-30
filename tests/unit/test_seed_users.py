from unittest.mock import MagicMock, patch

import bcrypt

from config.settings import Settings
from persistence.db.models import UserCounterpartyAccessORM, UserORM
from persistence.seed_users import ANALYST_BOOKS, seed_demo_users


def _session_factory():
    session = MagicMock()
    session_context = MagicMock()
    session_context.__enter__.return_value = session
    session_context.__exit__.return_value = None
    return session, MagicMock(return_value=session_context)


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        demo_approver_password="approver-pw",
        demo_manager_password="manager-pw",
        demo_analyst_password="analyst-pw",
        demo_auditor_password="auditor-pw",
    )


class TestSeedDemoUsers:
    def test_merges_the_demo_accounts_with_their_roles(self) -> None:
        session, session_factory = _session_factory()
        settings = _settings()

        with patch(
            "persistence.seed_users.get_session_factory", return_value=session_factory
        ) as mock_get_session_factory:
            seed_demo_users(settings)

        mock_get_session_factory.assert_called_once_with(settings)
        merged = [call.args[0] for call in session.merge.call_args_list]
        users = {u.username: u for u in merged if isinstance(u, UserORM)}
        assert {name: u.role for name, u in users.items()} == {
            "approver": "approver",
            "manager": "manager",
            "auditor": "auditor",
            "analyst1": "viewer",
            "analyst2": "viewer",
        }
        assert bcrypt.checkpw(b"approver-pw", users["approver"].password_hash.encode("utf-8"))
        assert bcrypt.checkpw(b"manager-pw", users["manager"].password_hash.encode("utf-8"))
        assert bcrypt.checkpw(b"auditor-pw", users["auditor"].password_hash.encode("utf-8"))
        assert bcrypt.checkpw(b"analyst-pw", users["analyst1"].password_hash.encode("utf-8"))
        session.commit.assert_called_once()

    def test_each_analyst_gets_exactly_their_own_book(self) -> None:
        session, session_factory = _session_factory()

        with patch("persistence.seed_users.get_session_factory", return_value=session_factory):
            seed_demo_users(_settings())

        merged = [call.args[0] for call in session.merge.call_args_list]
        access = {
            (a.username, a.counterparty_id)
            for a in merged
            if isinstance(a, UserCounterpartyAccessORM)
        }
        assert access == {(analyst, cp) for analyst, book in ANALYST_BOOKS.items() for cp in book}
        assert set(ANALYST_BOOKS["analyst1"]).isdisjoint(ANALYST_BOOKS["analyst2"])

    def test_users_are_flushed_before_access_rows(self) -> None:
        session, session_factory = _session_factory()
        order: list[str] = []
        session.flush.side_effect = lambda: order.append("flush")
        session.merge.side_effect = lambda row: order.append(type(row).__name__)

        with patch("persistence.seed_users.get_session_factory", return_value=session_factory):
            seed_demo_users(_settings())

        first_access = order.index("UserCounterpartyAccessORM")
        assert order.index("flush") < first_access
        assert "UserORM" not in order[first_access:]

    def test_defaults_to_get_settings_when_none_passed(self) -> None:
        session, session_factory = _session_factory()

        with (
            patch("persistence.seed_users.get_settings", return_value=_settings()),
            patch("persistence.seed_users.get_session_factory", return_value=session_factory),
        ):
            seed_demo_users()

        session.commit.assert_called_once()
