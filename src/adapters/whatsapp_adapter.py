"""WhatsApp Cloud API notifier (G6, MM-118, ADR-0016).

An in-process adapter behind the approval gate -- deliberately not an MCP
server: MCP servers in this project are read-only (MM-128), and a tool that
messages clients must never be reachable by an LLM (ADR-0016 amendment,
2026-10-05).

- Business-initiated notices use the approved `margin_call_notice` template:
  four body variables (reference, counterparty, amount, deadline), all
  formatted by code, plus the Acknowledge quick-reply button carrying the
  call's payload. Free-form text is used only when WHATSAPP_TEMPLATE_NAME is
  empty, and Meta delivers it only inside the 24-hour window.
- A `200` from `/messages` means *accepted*, not delivered: the receipt says
  "accepted" and delivery arrives later as a `statuses` webhook event.
- Any failure raises ClientDeliveryError. There is no fallback to Slack; the
  orchestrator escalates the call instead.
- The access token is never logged or put in an error message.
"""

from typing import Any

import httpx

from config.settings import Settings
from ports.notifier import ClientDeliveryError, ClientNotice, DeliveryReceipt

GRAPH_BASE_URL = "https://graph.facebook.com"


def normalize_phone(number: str) -> str:
    """WhatsApp ids are digits only, with the country code: "+1 555-0100" -> "15550100"."""
    return "".join(ch for ch in number if ch.isdigit())


class WhatsAppNotifier:
    def __init__(self, settings: Settings, http_client: httpx.Client | None = None) -> None:
        self._settings = settings
        self._http_client = http_client

    def recipient_for(self, counterparty_id: str) -> str:
        """Demo: every counterparty maps to the one verified test phone. A
        production deployment would look the counterparty up in a contact
        table (with consent records) instead."""
        recipient = normalize_phone(self._settings.whatsapp_recipient or "")
        if not recipient:
            raise ClientDeliveryError(f"No WhatsApp recipient configured for {counterparty_id}")
        return recipient

    def send(self, text: str) -> DeliveryReceipt:
        """Free-form text (24-hour window only) to the demo recipient."""
        recipient = self.recipient_for("demo")
        message_id = self._post(
            {
                "messaging_product": "whatsapp",
                "to": recipient,
                "type": "text",
                "text": {"preview_url": False, "body": text},
            }
        )
        return DeliveryReceipt(
            text=text, channel="whatsapp", message_id=message_id, status="accepted"
        )

    def send_notice(self, notice: ClientNotice) -> DeliveryReceipt:
        recipient = self.recipient_for(notice.counterparty_id)
        template = self._settings.whatsapp_template_name.strip()
        if not template:
            payload: dict[str, Any] = {
                "messaging_product": "whatsapp",
                "to": recipient,
                "type": "text",
                "text": {"preview_url": False, "body": notice.text},
                "biz_opaque_callback_data": notice.callback_data,
            }
            rendered = notice.text
        else:
            payload = {
                "messaging_product": "whatsapp",
                "to": recipient,
                "type": "template",
                "biz_opaque_callback_data": notice.callback_data,
                "template": {
                    "name": template,
                    "language": {"code": self._settings.whatsapp_template_language},
                    "components": [
                        {
                            "type": "body",
                            "parameters": [
                                {"type": "text", "text": value}
                                for value in (
                                    notice.reference,
                                    notice.counterparty_name,
                                    notice.amount,
                                    notice.deadline,
                                )
                            ],
                        },
                        {
                            "type": "button",
                            "sub_type": "quick_reply",
                            "index": "0",
                            "parameters": [{"type": "payload", "payload": notice.reply_payload}],
                        },
                    ],
                },
            }
            rendered = (
                f"[template {template}] {notice.reference} | {notice.counterparty_name} | "
                f"{notice.amount} | {notice.deadline}"
            )
        message_id = self._post(payload)
        return DeliveryReceipt(
            text=rendered, channel="whatsapp", message_id=message_id, status="accepted"
        )

    def _post(self, payload: dict[str, Any]) -> str:
        settings = self._settings
        if not settings.whatsapp_token or not settings.whatsapp_phone_number_id:
            raise ClientDeliveryError("WHATSAPP_TOKEN/WHATSAPP_PHONE_NUMBER_ID are not configured")
        url = (
            f"{GRAPH_BASE_URL}/{settings.whatsapp_graph_version}/"
            f"{settings.whatsapp_phone_number_id}/messages"
        )
        client = self._http_client or httpx.Client(timeout=15.0)
        try:
            response = client.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {settings.whatsapp_token}"},
            )
        except httpx.HTTPError as exc:
            raise ClientDeliveryError(f"WhatsApp send failed: {type(exc).__name__}") from exc
        finally:
            if self._http_client is None:
                client.close()
        if response.status_code >= 400:
            raise ClientDeliveryError(f"WhatsApp send rejected: {_meta_error(response)}")
        try:
            message_id = response.json()["messages"][0]["id"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ClientDeliveryError("WhatsApp send returned no message id") from exc
        return str(message_id)


def _meta_error(response: httpx.Response) -> str:
    """Meta's error code and message (never the request, which holds the token)."""
    try:
        error = response.json().get("error", {})
    except ValueError:
        return f"HTTP {response.status_code}"
    code = error.get("code")
    message = error.get("message") or error.get("error_user_msg") or ""
    return f"HTTP {response.status_code}, code {code}: {message}".strip()
