from unittest.mock import MagicMock, patch

import bcrypt

from config.settings import Settings
from persistence.db.models import UserORM
from persistence.seed_users import seed_demo_users


class TestSeedDemoUsers:
    def test_merges_and_commits_the_two_demo_accounts(self) -> None:
        session = MagicMock()
        session_context = MagicMock()
        session_context.__enter__.return_value = session
        session_context.__exit__.return_value = None
        session_factory = MagicMock(return_value=session_context)
        settings = Settings(
            _env_file=None,
            demo_approver_password="approver-pw",
            demo_viewer_password="viewer-pw",
        )

        with patch(
            "persistence.seed_users.get_session_factory", return_value=session_factory
        ) as mock_get_session_factory:
            seed_demo_users(settings)

        mock_get_session_factory.assert_called_once_with(settings)
        merged = [call.args[0] for call in session.merge.call_args_list]
        assert {u.username for u in merged} == {"approver", "viewer"}
        assert {u.role for u in merged} == {"approver", "viewer"}
        approver_row = next(u for u in merged if u.username == "approver")
        assert isinstance(approver_row, UserORM)
        assert bcrypt.checkpw(b"approver-pw", approver_row.password_hash.encode("utf-8"))
        session.commit.assert_called_once()

    def test_defaults_to_get_settings_when_none_passed(self) -> None:
        session = MagicMock()
        session_context = MagicMock()
        session_context.__enter__.return_value = session
        session_context.__exit__.return_value = None
        session_factory = MagicMock(return_value=session_context)
        settings = Settings(
            _env_file=None,
            demo_approver_password="approver-pw",
            demo_viewer_password="viewer-pw",
        )

        with (
            patch("persistence.seed_users.get_settings", return_value=settings),
            patch("persistence.seed_users.get_session_factory", return_value=session_factory),
        ):
            seed_demo_users()

        session.commit.assert_called_once()
