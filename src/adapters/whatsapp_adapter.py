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
- MM-144, WHATSAPP_NOTICE_PDF=on: the personalised PDF is uploaded first
  (`POST /{phone_number_id}/media`), then `margin_call_notice_v2` is sent
  with the PDF as its DOCUMENT header and the same four body variables and
  Acknowledge button as v1. A failed upload fails the send; the v1 template
  is not sent instead (no silent downgrade, ADR-0016).
- MM-143: the notice names its recipient (the counterparty's contact) or
  leaves it to WHATSAPP_RECIPIENT, the default. Numbers are never logged or
  put in an error message.
- A `200` from `/messages` means *accepted*, not delivered: the receipt says
  "accepted" and delivery arrives later as a `statuses` webhook event.
- Any failure raises ClientDeliveryError. There is no fallback to Slack; the
  orchestrator escalates the call instead.
- The access token is never logged or put in an error message.
"""

from typing import Any

import httpx

from adapters.factory import notice_pdf_enabled
from config.settings import Settings
from ports.notifier import ClientDeliveryError, ClientNotice, DeliveryReceipt

GRAPH_BASE_URL = "https://graph.facebook.com"
PDF_MIME = "application/pdf"


def normalize_phone(number: str) -> str:
    """WhatsApp ids are digits only, with the country code: "+1 555-0100" -> "15550100"."""
    return "".join(ch for ch in number if ch.isdigit())


class WhatsAppNotifier:
    def __init__(self, settings: Settings, http_client: httpx.Client | None = None) -> None:
        self._settings = settings
        self._http_client = http_client

    def recipient_for(self, counterparty_id: str) -> str:
        """The default recipient (WHATSAPP_RECIPIENT): used for a counterparty
        without an active contact (MM-143, persistence.contacts)."""
        recipient = normalize_phone(self._settings.whatsapp_recipient or "")
        if not recipient:
            raise ClientDeliveryError(f"No WhatsApp recipient configured for {counterparty_id}")
        return recipient

    def send(self, text: str) -> DeliveryReceipt:
        """Free-form text (24-hour window only) to the demo recipient."""
        recipient = self.recipient_for("demo")
        message_id = self._post_message(
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
        recipient = (
            normalize_phone(notice.recipient)
            if notice.recipient
            else self.recipient_for(notice.counterparty_id)
        )
        if not recipient:
            raise ClientDeliveryError(f"No WhatsApp recipient for {notice.counterparty_id}")
        if notice_pdf_enabled(self._settings):
            return self._send_pdf_notice(notice, recipient)

        template = self._settings.whatsapp_template_name.strip()
        if not template:
            payload: dict[str, Any] = {
                "messaging_product": "whatsapp",
                "to": recipient,
                "type": "text",
                "text": {"preview_url": False, "body": notice.text},
                "biz_opaque_callback_data": notice.callback_data,
            }
            message_id = self._post_message(payload)
            return DeliveryReceipt(
                text=notice.text, channel="whatsapp", message_id=message_id, status="accepted"
            )
        message_id = self._post_message(self._template_payload(recipient, notice, template))
        return DeliveryReceipt(
            text=_rendered(template, notice),
            channel="whatsapp",
            message_id=message_id,
            status="accepted",
            template=template,
        )

    def _send_pdf_notice(self, notice: ClientNotice, recipient: str) -> DeliveryReceipt:
        template = self._settings.whatsapp_pdf_template_name.strip()
        if not template:
            raise ClientDeliveryError("WHATSAPP_PDF_TEMPLATE_NAME is not configured")
        if not notice.document or not notice.document_filename:
            raise ClientDeliveryError("WHATSAPP_NOTICE_PDF is on but the notice has no PDF")
        media_id = self._upload_pdf(notice.document, notice.document_filename)
        header = {
            "type": "header",
            "parameters": [
                {
                    "type": "document",
                    "document": {"id": media_id, "filename": notice.document_filename},
                }
            ],
        }
        message_id = self._post_message(
            self._template_payload(recipient, notice, template, header=header)
        )
        return DeliveryReceipt(
            text=f"{_rendered(template, notice)} | {notice.document_filename}",
            channel="whatsapp",
            message_id=message_id,
            status="accepted",
            template=template,
        )

    def _template_payload(
        self,
        recipient: str,
        notice: ClientNotice,
        template: str,
        header: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        components: list[dict[str, Any]] = [header] if header else []
        components += [
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
        ]
        return {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "template",
            "biz_opaque_callback_data": notice.callback_data,
            "template": {
                "name": template,
                "language": {"code": self._settings.whatsapp_template_language},
                "components": components,
            },
        }

    def _upload_pdf(self, document: bytes, filename: str) -> str:
        """`POST /{phone_number_id}/media` (multipart): the media id Meta
        keeps the file under (for 30 days) for the template's header."""
        body = self._request(
            "media",
            "upload",
            data={"messaging_product": "whatsapp", "type": PDF_MIME},
            files={"file": (filename, document, PDF_MIME)},
        )
        media_id = body.get("id")
        if not media_id:
            raise ClientDeliveryError("WhatsApp media upload returned no media id")
        return str(media_id)

    def _post_message(self, payload: dict[str, Any]) -> str:
        body = self._request("messages", "send", json=payload)
        try:
            message_id = body["messages"][0]["id"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ClientDeliveryError("WhatsApp send returned no message id") from exc
        return str(message_id)

    def _request(self, endpoint: str, what: str, **kwargs: Any) -> dict[str, Any]:
        settings = self._settings
        if not settings.whatsapp_token or not settings.whatsapp_phone_number_id:
            raise ClientDeliveryError("WHATSAPP_TOKEN/WHATSAPP_PHONE_NUMBER_ID are not configured")
        url = (
            f"{GRAPH_BASE_URL}/{settings.whatsapp_graph_version}/"
            f"{settings.whatsapp_phone_number_id}/{endpoint}"
        )
        client = self._http_client or httpx.Client(timeout=30.0)
        try:
            response = client.post(
                url,
                headers={"Authorization": f"Bearer {settings.whatsapp_token}"},
                **kwargs,
            )
        except httpx.HTTPError as exc:
            raise ClientDeliveryError(f"WhatsApp {what} failed: {type(exc).__name__}") from exc
        finally:
            if self._http_client is None:
                client.close()
        if response.status_code >= 400:
            raise ClientDeliveryError(f"WhatsApp {what} rejected: {_meta_error(response)}")
        try:
            body = response.json()
        except ValueError as exc:
            raise ClientDeliveryError(f"WhatsApp {what} returned no JSON") from exc
        if not isinstance(body, dict):
            raise ClientDeliveryError(f"WhatsApp {what} returned an unexpected body")
        return body


def _rendered(template: str, notice: ClientNotice) -> str:
    return (
        f"[template {template}] {notice.reference} | {notice.counterparty_name} | "
        f"{notice.amount} | {notice.deadline}"
    )


def _meta_error(response: httpx.Response) -> str:
    """Meta's error code and message (never the request, which holds the token)."""
    try:
        error = response.json().get("error", {})
    except ValueError:
        return f"HTTP {response.status_code}"
    code = error.get("code")
    message = error.get("message") or error.get("error_user_msg") or ""
    return f"HTTP {response.status_code}, code {code}: {message}".strip()
