"""Notifier contract (MM-102; WhatsApp joined in G6, MM-118). Both client
channels deliver the same notice or fail loud -- never silently."""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import httpx
import pytest
from slack_sdk.errors import SlackApiError

from adapters.slack_adapter import SlackNotifier
from adapters.whatsapp_adapter import WhatsAppNotifier
from agents.client_notice import build_client_notice
from agents.communication import SlackDeliveryError
from config.settings import Settings
from ports.notifier import ClientDeliveryError


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


def _whatsapp(configured: bool = True, fail: bool = False):
    settings = Settings(
        _env_file=None,
        whatsapp_token="token" if configured else None,
        whatsapp_phone_number_id="123" if configured else None,
        whatsapp_recipient="15550100999",
    )
    response = (
        httpx.Response(400, json={"error": {"code": 131031, "message": "locked"}})
        if fail
        else httpx.Response(200, json={"messages": [{"id": "wamid.X"}]})
    )
    client = httpx.Client(transport=httpx.MockTransport(lambda request: response))
    return WhatsAppNotifier(settings, http_client=client)


NOTIFIERS = [
    pytest.param(_slack, SlackDeliveryError, id="slack"),
    pytest.param(_whatsapp, ClientDeliveryError, id="whatsapp"),
]

NOTICE = build_client_notice(
    thread_id="evt-1:CP-3",
    counterparty_id="CP-3",
    counterparty_name="Acme Capital",
    call_amount=2_500_000,
    currency="USD",
    deadline=datetime(2026, 10, 3, 17, 0, tzinfo=UTC),
    label="(TEST)",
)


@pytest.mark.parametrize(("make", "error"), NOTIFIERS)
def test_send_returns_receipt_for_the_same_text(make, error):
    receipt = make().send("Margin call notice for CP-3")

    assert receipt.text == "Margin call notice for CP-3"
    assert receipt.channel
    assert receipt.message_id


@pytest.mark.parametrize(("make", "error"), NOTIFIERS)
def test_send_notice_returns_a_receipt_naming_the_call(make, error):
    receipt = make().send_notice(NOTICE)

    assert receipt.message_id
    assert NOTICE.reference in receipt.text
    assert NOTICE.amount in receipt.text


@pytest.mark.parametrize(("make", "error"), NOTIFIERS)
def test_send_fails_loud_when_channel_not_configured(make, error):
    with pytest.raises(error):
        make(configured=False).send("notice")


@pytest.mark.parametrize(("make", "error"), NOTIFIERS)
def test_send_fails_loud_when_delivery_fails(make, error):
    with pytest.raises(error):
        make(fail=True).send_notice(NOTICE)
