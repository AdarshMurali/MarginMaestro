import pytest

from api.auth import Identity, require_user
from api.main import app


@pytest.fixture(autouse=True)
def _authenticated_reader():
    """MM-106: read endpoints require a logged-in user. Unit tests exercise
    each endpoint's own logic, so they run as a firm-wide user by default;
    tests of the auth/scope rules themselves use the `no_user_override`
    fixture to hit the real dependency."""
    app.dependency_overrides[require_user] = lambda: Identity(username="test-user", role="approver")
    yield
    app.dependency_overrides.pop(require_user, None)


@pytest.fixture
def no_user_override():
    app.dependency_overrides.pop(require_user, None)
