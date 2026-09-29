"""Notifier contract (MM-102). WhatsApp joins in G6."""

from unittest.mock import MagicMock

import pytest
from slack_sdk.errors import SlackApiError

from adapters.slack_adapter import SlackNotifier
from agents.communication import SlackDeliveryError
from config.settings import Settings


def _slack(configured: bool = True, fail: bool = False):
    settings = Settings(
        _env_file=None,
        slack_bot_token="xoxb-test" if configured else None,
        slack_channel_id="C123" if configured else None,
    )
    client = MagicMock()
    if fail:
        client.chat_postMessage.side_effect = SlackApiError("boom", {"error": "channel_not_found"})
    else:
        client.chat_postMessage.return_value = {"ts": "1727600000.000100"}
    return SlackNotifier(settings, slack_client=client)


NOTIFIERS = [pytest.param(_slack, id="slack")]


@pytest.mark.parametrize("make", NOTIFIERS)
def test_send_returns_receipt_for_the_same_text(make):
    receipt = make().send("Margin call notice for CP-3")

    assert receipt.text == "Margin call notice for CP-3"
    assert receipt.channel
    assert receipt.message_id


@pytest.mark.parametrize("make", NOTIFIERS)
def test_send_fails_loud_when_channel_not_configured(make):
    with pytest.raises(SlackDeliveryError):
        make(configured=False).send("notice")


@pytest.mark.parametrize("make", NOTIFIERS)
def test_send_fails_loud_when_delivery_fails(make):
    with pytest.raises(SlackDeliveryError):
        make(fail=True).send("notice")
