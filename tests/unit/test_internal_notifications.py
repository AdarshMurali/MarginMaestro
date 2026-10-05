"""G6 (MM-134): internal Slack traffic, each post exactly once."""

from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from adapters import factory
from adapters.slack_adapter import SlackNotifier
from adapters.whatsapp_adapter import WhatsAppNotifier
from agents import internal_notifications as internal
from agents.internal_notifications import InternalNotifier
from config.settings import Settings
from persistence.claims import claim_key, claim_once, release_claim
from persistence.db.models import Base


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def test_each_key_posts_once(session_factory):
    posts: list[str] = []
    notifier = InternalNotifier(posts.append, session_factory)

    assert notifier.post_once("a", "first") is True
    assert notifier.post_once("a", "again") is False
    assert notifier.post_once("b", "other") is True
    assert posts == ["first", "other"]


def test_disabled_notifier_posts_nothing():
    notifier = internal.disabled()

    assert notifier.enabled is False
    assert notifier.post_once("a", "text") is False


def test_a_failed_post_is_logged_not_raised_and_not_retried(session_factory):
    post = MagicMock(side_effect=RuntimeError("slack down"))
    notifier = InternalNotifier(post, session_factory)

    assert notifier.post_once("a", "text") is False
    assert notifier.post_once("a", "text") is False  # claim kept: no stale repost
    post.assert_called_once()


def test_claims_release_and_long_keys(session_factory):
    long_key = "k" * 500
    assert len(claim_key(long_key)) == 200
    assert claim_key("short") == "short"
    assert claim_once(session_factory, long_key) is True
    assert claim_once(session_factory, long_key) is False
    release_claim(session_factory, long_key)
    assert claim_once(session_factory, long_key) is True


def test_message_builders_carry_the_code_built_facts():
    assert "USD 1,234.50" in internal.approval_requested("MC-1", "Acme (CP-1)", 1234.5, "USD", None)
    assert "Why: big move" in internal.approval_requested("MC-1", "Acme", 1, "USD", "big move")
    assert "approved by alice" in internal.manager_approval_requested(
        "MC-1", "Acme", 10, "USD", "alice"
    )
    assert "an approver" in internal.manager_approval_requested("MC-1", "Acme", 10, "USD", None)
    assert "wamid.1" in internal.client_notified(
        "MC-1", "Acme", "USD 1.00", "soon", "WhatsApp", "wamid.1"
    )
    assert "SLA met" in internal.client_acknowledged("MC-1", "Acme", "USD 1.00")
    assert "No other channel" in internal.delivery_failed("MC-1", "Acme", "locked")
    assert "INC001" in internal.escalated("MC-1", "Acme", "USD 1.00", "INC001", "late")
    reply = internal.client_reply("+…0999", None, None, False, "Blocked.")
    assert "(text withheld)" in reply and "no call identified" in reply


def test_mask_phone_keeps_only_the_last_four_digits():
    assert internal.mask_phone("+1 555 010 0999") == "+…0999"
    assert internal.mask_phone("12") == "+…"


def test_daily_run_summary_counts_and_lists_calls():
    text = internal.daily_run_summary(
        "daily-margin-run:2026-10-05",
        3,
        [
            {
                "counterparty_id": "CP-1",
                "action": "started",
                "breached": True,
                "call_amount": 250_785.91,
            },
            {
                "counterparty_id": "CP-2",
                "action": "started",
                "breached": False,
                "call_amount": None,
            },
            {"counterparty_id": "CP-3", "action": "updated", "breached": True, "call_amount": None},
            {"counterparty_id": "CP-4", "action": "unchanged"},
        ],
    )

    assert "3 counterparties evaluated, 1 call(s) raised" in text
    assert "1 open call(s) updated, 1 left unchanged" in text
    assert "CP-1: started, call 250,785.91" in text
    assert "CP-3: updated, call n/a" in text
    assert "CP-2" not in text


# --- factory -----------------------------------------------------------------------------


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_client_notifier_whatsapp_is_the_whatsapp_adapter():
    assert isinstance(factory.get_notifier(_settings(client_notifier="whatsapp")), WhatsAppNotifier)
    assert isinstance(factory.get_notifier(_settings()), SlackNotifier)


def test_internal_notifier_defaults_to_none_and_slack_is_opt_in(session_factory):
    assert factory.get_internal_notifier(_settings()).enabled is False
    notifier = factory.get_internal_notifier(_settings(internal_notifier="slack"), session_factory)
    assert notifier.enabled is True


def test_unknown_internal_notifier_fails_loud():
    with pytest.raises(ValueError, match="INTERNAL_NOTIFIER"):
        factory.get_internal_notifier(_settings(internal_notifier="email"))
