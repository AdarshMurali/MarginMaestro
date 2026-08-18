from unittest.mock import patch

import pytest

from agents.communication import NotificationResult, SlackDeliveryError
from mcp_servers.slack_notifier import send_margin_call_notice


class TestSendMarginCallNoticeTool:
    def test_forwards_text_and_serializes_result(self) -> None:
        result = NotificationResult(
            notice_text="Dear CP-3, ...", slack_channel="C0BMCAL6L74", slack_ts="1234.5678"
        )

        with patch(
            "mcp_servers.slack_notifier.send_slack_notice", return_value=result
        ) as mock_send:
            output = send_margin_call_notice("Dear CP-3, ...")

        mock_send.assert_called_once_with("Dear CP-3, ...")
        assert output == result.model_dump()

    def test_slack_delivery_error_propagates_not_swallowed(self) -> None:
        with (
            patch(
                "mcp_servers.slack_notifier.send_slack_notice",
                side_effect=SlackDeliveryError("Slack delivery failed: channel_not_found"),
            ),
            pytest.raises(SlackDeliveryError, match="channel_not_found"),
        ):
            send_margin_call_notice("Dear CP-3, ...")
