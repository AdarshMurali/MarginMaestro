from unittest.mock import MagicMock

import pytest
from slack_sdk.errors import SlackApiError

from agents.communication import (
    NoticeDraftingError,
    SlackDeliveryError,
    draft_margin_call_notice,
    draft_sla_met_notice,
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


class _ScriptedLLM:
    """Returns the scripted drafts in order; records every request it got."""

    def __init__(self, *drafts: str | None) -> None:
        self._drafts = list(drafts)
        self.requests: list[str] = []

    def complete(self, system: str, user: str) -> str | None:
        self.requests.append(system + "\n" + user)
        return self._drafts.pop(0)

    def parse(self, system, user, schema):  # pragma: no cover - not used here
        raise NotImplementedError


GOOD_NOTICE = (
    "Dear {COUNTERPARTY}, a margin call of {CALL_AMOUNT} is due under your CSA "
    "(threshold {THRESHOLD}, minimum transfer amount {MTA}). Please settle promptly."
)


def _draft(llm: _ScriptedLLM, amount: float = 474_000.0) -> str:
    return draft_margin_call_notice(
        "CP-3", amount, "USD", CSA_TERMS, settings=Settings(_env_file=None), llm=llm
    )


class TestDraftMarginCallNotice:
    """MM-116: the model never sees or writes a figure."""

    def test_no_figure_is_ever_sent_to_the_model(self) -> None:
        llm = _ScriptedLLM(GOOD_NOTICE)

        _draft(llm)

        sent = llm.requests[0]
        for figure in ("474", "100,000", "10,000", "CP-3"):
            assert figure not in sent
        assert "{CALL_AMOUNT}" in sent

    def test_code_fills_in_the_calculated_figures(self) -> None:
        notice = _draft(_ScriptedLLM(GOOD_NOTICE))

        assert notice == (
            "Dear CP-3, a margin call of USD 474,000.00 is due under your CSA "
            "(threshold USD 100,000.00, minimum transfer amount USD 10,000.00). "
            "Please settle promptly."
        )

    def test_works_through_the_openai_client_path_too(self) -> None:
        client = _mock_openai_client("  " + GOOD_NOTICE + "  ")

        notice = draft_margin_call_notice(
            "CP-3",
            474_000.0,
            "USD",
            CSA_TERMS,
            openai_client=client,
            settings=Settings(_env_file=None),
        )

        assert notice.startswith("Dear CP-3, a margin call of USD 474,000.00")

    @pytest.mark.parametrize(
        ("bad_draft", "problem"),
        [
            ("Dear {COUNTERPARTY}, please pay USD 474,000.", "figures"),
            ("Dear {COUNTERPARTY}, pay {CALL_AMOUNT} within 24 hours.", "figures"),
            ("Dear {COUNTERPARTY}, please settle promptly.", "missing placeholders"),
            ("Dear {COUNTERPARTY}, pay {CALL_AMOUNT} plus {PENALTY}.", "unknown placeholders"),
        ],
    )
    def test_unsafe_draft_is_retried_once_with_the_reason(self, bad_draft, problem) -> None:
        llm = _ScriptedLLM(bad_draft, GOOD_NOTICE)

        notice = _draft(llm)

        assert "USD 474,000.00" in notice
        assert len(llm.requests) == 2
        assert "rejected" in llm.requests[1] and problem in llm.requests[1]

    def test_two_unsafe_drafts_stop_the_notice(self) -> None:
        llm = _ScriptedLLM(
            "{COUNTERPARTY}: pay {CALL_AMOUNT} or USD 1.",
            "{COUNTERPARTY}: pay {CALL_AMOUNT} or USD 2.",
        )

        with pytest.raises(NoticeDraftingError, match="CP-3.*figures"):
            _draft(llm)

    def test_empty_drafts_stop_the_notice(self) -> None:
        with pytest.raises(NoticeDraftingError, match="empty draft"):
            _draft(_ScriptedLLM("   ", None))


class TestDraftSlaMetNotice:
    def test_no_figure_is_sent_and_code_fills_it_in(self) -> None:
        llm = _ScriptedLLM("{COUNTERPARTY} met its margin call of {CALL_AMOUNT} in full.")

        notice = draft_sla_met_notice(
            "CP-3", 474_000.0, "USD", settings=Settings(_env_file=None), llm=llm
        )

        assert "474" not in llm.requests[0]
        assert notice == "CP-3 met its margin call of USD 474,000.00 in full."

    def test_draft_without_the_amount_placeholder_is_rejected(self) -> None:
        llm = _ScriptedLLM("{COUNTERPARTY} has met its obligation.", "Done.")

        with pytest.raises(NoticeDraftingError, match="missing placeholders"):
            draft_sla_met_notice(
                "CP-3", 474_000.0, "USD", settings=Settings(_env_file=None), llm=llm
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
