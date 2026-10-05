"""G6 (MM-118): the WhatsApp client notifier and the code-built notice."""

import json
from datetime import UTC, datetime

import httpx
import pytest

from adapters.whatsapp_adapter import WhatsAppNotifier, normalize_phone
from agents.client_notice import (
    ack_payload,
    build_client_notice,
    call_reference,
    display_name,
    thread_from_ack_payload,
)
from config.settings import Settings
from ports.notifier import ClientDeliveryError

TOKEN = "EAAG-test-token-never-printed"
THREAD = "evt-1:CP-3"


def _settings(**overrides) -> Settings:
    values = {
        "whatsapp_token": TOKEN,
        "whatsapp_phone_number_id": "1382503808268641",
        "whatsapp_recipient": "+1 555 010 0999",
        "whatsapp_graph_version": "v23.0",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _notice():
    return build_client_notice(
        thread_id=THREAD,
        counterparty_id="CP-3",
        counterparty_name="Acme Capital",
        call_amount=2_500_000,
        currency="USD",
        deadline=datetime(2026, 10, 3, 17, 0, tzinfo=UTC),
        label="(TEST)",
    )


class _Recorder:
    def __init__(self, response: httpx.Response | Exception) -> None:
        self.requests: list[httpx.Request] = []
        self._response = response

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


def _client(response: httpx.Response | Exception) -> tuple[httpx.Client, _Recorder]:
    recorder = _Recorder(response)
    return httpx.Client(transport=httpx.MockTransport(recorder.handler)), recorder


def _accepted() -> httpx.Response:
    return httpx.Response(200, json={"messages": [{"id": "wamid.ABC"}]})


# --- the notice: every value formatted by code --------------------------------------


def test_notice_fields_are_formatted_by_code():
    notice = _notice()

    assert notice.reference == call_reference(THREAD)
    assert notice.counterparty_name == "Acme Capital (TEST)"
    assert notice.amount == "USD 2,500,000.00"
    assert notice.deadline == "17:00 UTC on 3 October 2026"
    assert notice.reply_payload == f"ack:{THREAD}"
    assert notice.callback_data == THREAD
    assert "Synthetic data" in notice.text


def test_call_reference_is_short_stable_and_distinct():
    reference = call_reference(THREAD)

    assert reference.startswith("MC-") and len(reference) == 11
    assert reference == call_reference(THREAD)
    assert reference != call_reference("evt-2:CP-3")


def test_ack_payload_round_trips_and_rejects_other_payloads():
    assert thread_from_ack_payload(ack_payload(THREAD)) == THREAD
    assert thread_from_ack_payload("Acknowledge") is None
    assert thread_from_ack_payload("ack:no-colon") is None


def test_ack_payload_too_long_fails_loud():
    with pytest.raises(ValueError, match="too long"):
        ack_payload("e" * 200 + ":CP-1")


def test_display_name_without_label_is_the_plain_name():
    assert display_name("Acme Capital", "") == "Acme Capital"


def test_notice_without_label_has_no_synthetic_note():
    notice = build_client_notice(
        thread_id=THREAD,
        counterparty_id="CP-3",
        counterparty_name="Acme Capital",
        call_amount=10,
        currency="EUR",
        deadline=datetime(2026, 10, 3, 17, 0, tzinfo=UTC),
        label="",
    )
    assert notice.counterparty_name == "Acme Capital"
    assert "Synthetic" not in notice.text


# --- the adapter ---------------------------------------------------------------------


def test_template_send_puts_the_four_variables_in_order_and_the_ack_payload():
    client, recorder = _client(_accepted())

    receipt = WhatsAppNotifier(_settings(), http_client=client).send_notice(_notice())

    assert receipt.channel == "whatsapp"
    assert receipt.message_id == "wamid.ABC"
    assert receipt.status == "accepted"  # 200 = accepted, not delivered
    request = recorder.requests[0]
    assert str(request.url) == "https://graph.facebook.com/v23.0/1382503808268641/messages"
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    body = json.loads(request.content)
    assert body["to"] == "15550100999"
    assert body["type"] == "template"
    assert body["biz_opaque_callback_data"] == THREAD
    template = body["template"]
    assert template["name"] == "margin_call_notice"
    assert template["language"] == {"code": "en_US"}
    params = [p["text"] for p in template["components"][0]["parameters"]]
    assert params == [
        call_reference(THREAD),
        "Acme Capital (TEST)",
        "USD 2,500,000.00",
        "17:00 UTC on 3 October 2026",
    ]
    button = template["components"][1]
    assert button["sub_type"] == "quick_reply"
    assert button["parameters"] == [{"type": "payload", "payload": f"ack:{THREAD}"}]
    assert TOKEN not in receipt.text


def test_template_language_and_version_come_from_settings():
    client, recorder = _client(_accepted())
    settings = _settings(whatsapp_template_language="en", whatsapp_graph_version="v24.0")

    WhatsAppNotifier(settings, http_client=client).send_notice(_notice())

    body = json.loads(recorder.requests[0].content)
    assert body["template"]["language"] == {"code": "en"}
    assert "/v24.0/" in str(recorder.requests[0].url)


def test_without_a_template_name_the_notice_goes_as_free_form_text():
    client, recorder = _client(_accepted())

    receipt = WhatsAppNotifier(
        _settings(whatsapp_template_name=""), http_client=client
    ).send_notice(_notice())

    body = json.loads(recorder.requests[0].content)
    assert body["type"] == "text"
    assert body["text"]["body"] == _notice().text
    assert receipt.text == _notice().text


def test_plain_send_is_free_form_text():
    client, recorder = _client(_accepted())

    receipt = WhatsAppNotifier(_settings(), http_client=client).send("hello")

    assert json.loads(recorder.requests[0].content)["text"]["body"] == "hello"
    assert receipt.status == "accepted"


@pytest.mark.parametrize(
    "overrides",
    [{"whatsapp_token": None}, {"whatsapp_phone_number_id": None}, {"whatsapp_recipient": None}],
)
def test_missing_configuration_fails_loud(overrides):
    client, recorder = _client(_accepted())

    with pytest.raises(ClientDeliveryError, match="configured"):
        WhatsAppNotifier(_settings(**overrides), http_client=client).send_notice(_notice())
    assert recorder.requests == []


def test_meta_rejection_raises_with_code_but_never_the_token():
    response = httpx.Response(
        400, json={"error": {"code": 131047, "message": "Re-engagement message"}}
    )
    client, _ = _client(response)

    with pytest.raises(ClientDeliveryError) as exc_info:
        WhatsAppNotifier(_settings(), http_client=client).send_notice(_notice())

    assert "131047" in str(exc_info.value)
    assert TOKEN not in str(exc_info.value)


def test_non_json_error_body_still_raises():
    client, _ = _client(httpx.Response(502, text="bad gateway"))

    with pytest.raises(ClientDeliveryError, match="HTTP 502"):
        WhatsAppNotifier(_settings(), http_client=client).send_notice(_notice())


def test_network_error_raises():
    client, _ = _client(httpx.ConnectError("down"))

    with pytest.raises(ClientDeliveryError, match="ConnectError"):
        WhatsAppNotifier(_settings(), http_client=client).send_notice(_notice())


def test_response_without_message_id_raises():
    client, _ = _client(httpx.Response(200, json={"messages": []}))

    with pytest.raises(ClientDeliveryError, match="no message id"):
        WhatsAppNotifier(_settings(), http_client=client).send_notice(_notice())


def test_own_http_client_is_closed_after_the_send(monkeypatch):
    created: list[httpx.Client] = []
    transport = httpx.MockTransport(lambda request: _accepted())
    real_client = httpx.Client

    def _factory(*args, **kwargs):
        client = real_client(transport=transport)
        created.append(client)
        return client

    monkeypatch.setattr("adapters.whatsapp_adapter.httpx.Client", _factory)

    WhatsAppNotifier(_settings()).send_notice(_notice())

    assert created and created[0].is_closed


def test_normalize_phone_keeps_digits_only():
    assert normalize_phone("+1 (555) 010-0999") == "15550100999"
