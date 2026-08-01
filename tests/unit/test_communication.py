from unittest.mock import MagicMock

import pytest
from slack_sdk.errors import SlackApiError

from agents.communication import (
    NoticeDraftingError,
    SlackDeliveryError,
    draft_margin_call_notice,
    send_slack_notice,
)
from calc.models import CSATerms
from config.settings import Settings

CSA_TERMS = CSATerms(threshold=100_000.0, mta=10_000.0, currency="USD")


def _mock_openai_client(text: str | None) -> MagicMock:
    client = MagicMock()
    client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=text))]
    )
    return client


class TestDraftMarginCallNotice:
    def test_prompt_carries_the_given_figures_verbatim(self) -> None:
        client = _mock_openai_client("Dear CP-3, a margin call notice.")

        draft_margin_call_notice(
            "CP-3",
            474_000.0,
            "USD",
            CSA_TERMS,
            openai_client=client,
            settings=Settings(_env_file=None),
        )

        _, kwargs = client.chat.completions.create.call_args
        user_message = kwargs["messages"][1]["content"]
        assert "CP-3" in user_message
        assert "474,000.00" in user_message
        assert "100,000.00" in user_message
        assert "10,000.00" in user_message

    def test_returns_stripped_llm_text(self) -> None:
        client = _mock_openai_client("  Dear CP-3, a margin call notice.  \n")

        result = draft_margin_call_notice(
            "CP-3",
            474_000.0,
            "USD",
            CSA_TERMS,
            openai_client=client,
            settings=Settings(_env_file=None),
        )

        assert result == "Dear CP-3, a margin call notice."

    def test_empty_llm_response_raises(self) -> None:
        client = _mock_openai_client("   ")

        with pytest.raises(NoticeDraftingError, match="CP-3"):
            draft_margin_call_notice(
                "CP-3",
                474_000.0,
                "USD",
                CSA_TERMS,
                openai_client=client,
                settings=Settings(_env_file=None),
            )


class TestSendSlackNotice:
    def _configured_settings(self) -> Settings:
        return Settings(
            _env_file=None, slack_bot_token="xoxb-test-token", slack_channel_id="C0BMCAL6L74"
        )

    def test_posts_to_the_configured_channel(self) -> None:
        client = MagicMock()
        client.chat_postMessage.return_value = {"ts": "1234.5678"}

        result = send_slack_notice(
            "Dear CP-3, ...", settings=self._configured_settings(), slack_client=client
        )

        client.chat_postMessage.assert_called_once_with(
            channel="C0BMCAL6L74", text="Dear CP-3, ..."
        )
        assert result.slack_channel == "C0BMCAL6L74"
        assert result.slack_ts == "1234.5678"
        assert result.notice_text == "Dear CP-3, ..."

    def test_raises_when_slack_is_not_configured(self) -> None:
        with pytest.raises(SlackDeliveryError):
            send_slack_notice("text", settings=Settings(_env_file=None), slack_client=MagicMock())

    def test_raises_on_slack_api_error(self) -> None:
        client = MagicMock()
        client.chat_postMessage.side_effect = SlackApiError(
            "channel_not_found", response={"error": "channel_not_found"}
        )

        with pytest.raises(SlackDeliveryError, match="channel_not_found"):
            send_slack_notice("text", settings=self._configured_settings(), slack_client=client)
