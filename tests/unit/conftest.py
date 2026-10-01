import pytest

from api import rate_limit
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


@pytest.fixture(autouse=True)
def _fresh_rate_limiter(monkeypatch):
    """MM-117: the action limiter is process-wide; unit tests make many calls
    as the same test user, so each test gets an empty window."""
    monkeypatch.setattr(rate_limit, "ACTION_LIMITER", rate_limit.SlidingWindowLimiter())
    import api.main

    monkeypatch.setattr(api.main, "ACTION_LIMITER", rate_limit.ACTION_LIMITER)
