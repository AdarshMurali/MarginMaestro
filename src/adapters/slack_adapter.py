from slack_sdk import WebClient

from config.settings import Settings
from ports.notifier import ClientNotice, DeliveryReceipt


class SlackNotifier:
    """`Notifier` over the existing Slack send path (agents.communication).
    Kept as a wrapper, not a rewrite, so the orchestrator's Slack behaviour
    (CLIENT_NOTIFIER=slack, the AWS default) and its tests stay untouched.
    Since G6 Slack is also the internal channel (agents.internal_notifications)."""

    def __init__(self, settings: Settings, slack_client: WebClient | None = None) -> None:
        self._settings = settings
        self._slack_client = slack_client

    def send(self, text: str) -> DeliveryReceipt:
        from agents.communication import send_slack_notice

        result = send_slack_notice(text, settings=self._settings, slack_client=self._slack_client)
        return DeliveryReceipt(
            text=result.notice_text,
            channel=result.slack_channel or "slack",
            message_id=result.slack_ts or "",
        )

    def send_notice(self, notice: ClientNotice) -> DeliveryReceipt:
        return self.send(notice.text)
