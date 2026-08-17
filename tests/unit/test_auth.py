from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import bcrypt
import jwt
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.auth import JWT_ALGORITHM, require_approver, require_manager, verify_credentials
from api.main import app
from config.settings import Settings
from persistence.db.models import Base, UserORM

TEST_SECRET = "test-secret"


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _seed_user(session_factory, username: str, password: str, role: str) -> None:
    with session_factory() as session:
        password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        session.merge(UserORM(username=username, password_hash=password_hash, role=role))
        session.commit()


def _token(
    role: str, sub: str = "someone", secret: str = TEST_SECRET, expired: bool = False
) -> str:
    exp = datetime.now(UTC) + (timedelta(minutes=-5) if expired else timedelta(minutes=15))
    return jwt.encode({"sub": sub, "role": role, "exp": exp}, secret, algorithm=JWT_ALGORITHM)


class TestVerifyCredentials:
    def test_correct_password_returns_the_role(self, session_factory) -> None:
        _seed_user(session_factory, "approver", "correct-horse", "approver")

        with session_factory() as session:
            assert verify_credentials("approver", "correct-horse", session) == "approver"

    def test_wrong_password_returns_none(self, session_factory) -> None:
        _seed_user(session_factory, "approver", "correct-horse", "approver")

        with session_factory() as session:
            assert verify_credentials("approver", "wrong", session) is None

    def test_unknown_username_returns_none(self, session_factory) -> None:
        with session_factory() as session:
            assert verify_credentials("no-such-user", "anything", session) is None


class TestRequireApprover:
    def test_valid_approver_token_returns_the_username(self) -> None:
        with patch(
            "api.auth.get_settings",
            return_value=Settings(_env_file=None, auth_backend_secret=TEST_SECRET),
        ):
            username = require_approver(f"Bearer {_token('approver', sub='alice')}")

        assert username == "alice"

    def test_viewer_token_is_forbidden(self) -> None:
        with (
            patch(
                "api.auth.get_settings",
                return_value=Settings(_env_file=None, auth_backend_secret=TEST_SECRET),
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            require_approver(f"Bearer {_token('viewer')}")

        assert exc_info.value.status_code == 403

    def test_missing_header_is_unauthorized(self) -> None:
        with (
            patch(
                "api.auth.get_settings",
                return_value=Settings(_env_file=None, auth_backend_secret=TEST_SECRET),
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            require_approver(None)

        assert exc_info.value.status_code == 401

    def test_wrong_signature_is_unauthorized(self) -> None:
        with (
            patch(
                "api.auth.get_settings",
                return_value=Settings(_env_file=None, auth_backend_secret=TEST_SECRET),
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            require_approver(f"Bearer {_token('approver', secret='wrong-secret')}")

        assert exc_info.value.status_code == 401

    def test_expired_token_is_unauthorized(self) -> None:
        with (
            patch(
                "api.auth.get_settings",
                return_value=Settings(_env_file=None, auth_backend_secret=TEST_SECRET),
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            require_approver(f"Bearer {_token('approver', expired=True)}")

        assert exc_info.value.status_code == 401

    def test_missing_backend_secret_is_a_server_error(self) -> None:
        with (
            patch(
                "api.auth.get_settings",
                return_value=Settings(_env_file=None, auth_backend_secret=None),
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            require_approver(f"Bearer {_token('approver')}")

        assert exc_info.value.status_code == 500


class TestRequireManager:
    def test_valid_manager_token_returns_the_username(self) -> None:
        with patch(
            "api.auth.get_settings",
            return_value=Settings(_env_file=None, auth_backend_secret=TEST_SECRET),
        ):
            username = require_manager(f"Bearer {_token('manager', sub='bob')}")

        assert username == "bob"

    def test_approver_token_is_forbidden(self) -> None:
        """The two roles are distinct -- an approver token doesn't also
        satisfy the manager gate, even though the same human could in
        principle hold both roles in real life."""
        with (
            patch(
                "api.auth.get_settings",
                return_value=Settings(_env_file=None, auth_backend_secret=TEST_SECRET),
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            require_manager(f"Bearer {_token('approver')}")

        assert exc_info.value.status_code == 403

    def test_missing_header_is_unauthorized(self) -> None:
        with (
            patch(
                "api.auth.get_settings",
                return_value=Settings(_env_file=None, auth_backend_secret=TEST_SECRET),
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            require_manager(None)

        assert exc_info.value.status_code == 401


class TestGatingAgainstTheRealDependency:
    """No dependency_overrides here -- exercises the real require_approver
    wired into the app, end to end through a real HTTP request."""

    client = TestClient(app)

    def test_approve_without_a_token_is_rejected(self) -> None:
        with patch(
            "api.auth.get_settings",
            return_value=Settings(_env_file=None, auth_backend_secret=TEST_SECRET),
        ):
            response = self.client.post(
                "/margin-calls/evt-1:CP-1/approve", json={"decision": "approved"}
            )

        assert response.status_code == 401

    def test_approve_with_a_viewer_token_is_forbidden(self) -> None:
        with patch(
            "api.auth.get_settings",
            return_value=Settings(_env_file=None, auth_backend_secret=TEST_SECRET),
        ):
            response = self.client.post(
                "/margin-calls/evt-1:CP-1/approve",
                json={"decision": "approved"},
                headers={"Authorization": f"Bearer {_token('viewer')}"},
            )

        assert response.status_code == 403

    def test_approve_with_a_valid_approver_token_reaches_the_endpoint(self) -> None:
        with (
            patch(
                "api.auth.get_settings",
                return_value=Settings(_env_file=None, auth_backend_secret=TEST_SECRET),
            ),
            patch("api.main.get_orchestrator_graph", return_value=MagicMock()),
            patch("api.main.resume_run", return_value={"approval_decision": "approved"}),
        ):
            response = self.client.post(
                "/margin-calls/evt-1:CP-1/approve",
                json={"decision": "approved"},
                headers={"Authorization": f"Bearer {_token('approver')}"},
            )

        assert response.status_code == 200

    def test_manager_approve_with_an_approver_token_is_forbidden(self) -> None:
        with patch(
            "api.auth.get_settings",
            return_value=Settings(_env_file=None, auth_backend_secret=TEST_SECRET),
        ):
            response = self.client.post(
                "/margin-calls/evt-1:CP-1/manager-approve",
                json={"decision": "approved"},
                headers={"Authorization": f"Bearer {_token('approver')}"},
            )

        assert response.status_code == 403

    def test_manager_approve_with_a_valid_manager_token_reaches_the_endpoint(self) -> None:
        mock_graph = MagicMock()
        mock_graph.get_state.return_value.values = {"first_approver_username": "alice"}
        with (
            patch(
                "api.auth.get_settings",
                return_value=Settings(_env_file=None, auth_backend_secret=TEST_SECRET),
            ),
            patch("api.main.get_orchestrator_graph", return_value=mock_graph),
            patch("api.main.resume_run", return_value={"approval_decision": "approved"}),
        ):
            response = self.client.post(
                "/margin-calls/evt-1:CP-1/manager-approve",
                json={"decision": "approved"},
                headers={"Authorization": f"Bearer {_token('manager', sub='bob')}"},
            )

        assert response.status_code == 200


class TestAuthVerifyEndpoint:
    client = TestClient(app)

    def test_correct_credentials_return_the_role(self) -> None:
        session_factory = MagicMock()
        session = MagicMock()
        session_factory.return_value.__enter__.return_value = session
        with (
            patch("api.main.get_db_session_factory", return_value=session_factory),
            patch("api.main.verify_credentials", return_value="approver") as mock_verify,
        ):
            response = self.client.post(
                "/auth/verify", json={"username": "approver", "password": "x"}
            )

        assert response.status_code == 200
        assert response.json() == {"username": "approver", "role": "approver"}
        mock_verify.assert_called_once_with("approver", "x", session)

    def test_wrong_credentials_return_401(self) -> None:
        session_factory = MagicMock()
        session_factory.return_value.__enter__.return_value = MagicMock()
        with (
            patch("api.main.get_db_session_factory", return_value=session_factory),
            patch("api.main.verify_credentials", return_value=None),
        ):
            response = self.client.post(
                "/auth/verify", json={"username": "approver", "password": "wrong"}
            )

        assert response.status_code == 401
