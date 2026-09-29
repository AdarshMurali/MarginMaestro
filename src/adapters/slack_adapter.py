from slack_sdk import WebClient

from config.settings import Settings
from ports.notifier import DeliveryReceipt


class SlackNotifier:
    """`Notifier` over the existing Slack send path (agents.communication).
    Kept as a wrapper, not a rewrite, so the orchestrator's current Slack
    behaviour and its tests stay untouched until G6 routes client notices."""

    def __init__(self, settings: Settings, slack_client: WebClient | None = None) -> None:
        self._settings = settings
        self._slack_client = slack_client

    def send(self, text: str) -> DeliveryReceipt:
        from agents.communication import send_slack_notice

        result = send_slack_notice(text, settings=self._settings, slack_client=self._slack_client)
        return DeliveryReceipt(
            text=result.notice_text, channel=result.slack_channel, message_id=result.slack_ts
        )
