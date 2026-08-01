"""Real Slack + real OpenAI calls. Excluded from the default/CI test run (see
the `live` marker in pyproject.toml) since they depend on real external
services and post a real message to the configured Slack channel.

Run explicitly with: pytest -m live tests/integration/test_communication_live.py
"""

import pytest

from agents.communication import draft_margin_call_notice, send_slack_notice
from calc.models import CSATerms
from config.settings import get_settings

pytestmark = pytest.mark.live


def test_drafts_and_sends_a_real_margin_call_notice() -> None:
    settings = get_settings()
    csa_terms = CSATerms(threshold=100_000.0, mta=10_000.0, currency="USD")

    notice_text = draft_margin_call_notice(
        "CP-TEST", 474_000.0, "USD", csa_terms, settings=settings
    )
    assert "474,000" in notice_text or "474000" in notice_text

    result = send_slack_notice(notice_text, settings=settings)

    assert result.slack_ts
    assert result.slack_channel == settings.slack_channel_id
