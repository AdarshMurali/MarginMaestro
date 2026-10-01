"""Communication Agent (MM-41, docs/AGENTS.md #6): drafts the client-facing
margin-call notice via the LLM, then -- only after human approval -- sends it
through Slack. Never sends before the approval gate. Message content is
drafted by the LLM; the send itself is deterministic code (CLAUDE.md golden
rule 1 -- the LLM never computes or alters a figure, only phrases the notice
around numbers it's given).

MM-116: the model never sees the figures at all. It drafts with placeholders
({CALL_AMOUNT}, ...); code checks the draft (required placeholders present,
no unknown ones, no digits anywhere) and only then fills in the values from
the calculation. A wrong amount can't be sent because the model can't write
one."""

import re

from openai import OpenAI
from pydantic import BaseModel
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from adapters.factory import get_llm
from calc.models import CSATerms
from config.settings import Settings, get_settings
from ports.llm import LLMClient

SYSTEM_PROMPT = (
    "You draft formal, concise client-facing margin call notices for a bank "
    "operations team. You are never given figures: write the placeholders you "
    "are given (for example {CALL_AMOUNT}) exactly as written wherever that "
    "value belongs, and they will be filled in afterwards. Never write any "
    "digits yourself -- write durations and counts in words. Don't mention "
    "attachments or documents you weren't given. 1-2 short "
    "professional paragraphs, no markdown, no subject line (this is posted "
    "directly to a chat channel, not emailed)."
)

_PLACEHOLDER = re.compile(r"\{([A-Z_]+)\}")


def _validate_draft(draft: str, allowed: set[str], required: set[str]) -> str | None:
    """The reason the draft is unusable, or None if it's safe to fill in."""
    used = set(_PLACEHOLDER.findall(draft))
    if unknown := used - allowed:
        return f"unknown placeholders {sorted(unknown)}"
    if missing := required - used:
        return f"missing placeholders {sorted(missing)}"
    if re.search(r"\d", _PLACEHOLDER.sub("", draft)):
        return "the draft contains figures that did not come from the calculation"
    return None


def _draft_with_placeholders(
    llm: LLMClient,
    request: str,
    values: dict[str, str],
    required: set[str],
    what: str,
) -> str:
    """Ask for a draft, validate it (one retry naming the problem), then fill
    in the placeholders. Fails loud -- an unusable draft is never sent."""
    prompt = request
    problem: str | None = "empty draft"
    for _ in range(2):
        text = (llm.complete(SYSTEM_PROMPT, prompt) or "").strip()
        problem = _validate_draft(text, set(values), required) if text else "empty draft"
        if problem is None:
            return _PLACEHOLDER.sub(lambda m: values[m.group(1)], text)
        prompt = f"{request}\n\nYour previous draft was rejected: {problem}. Try again."
    raise NoticeDraftingError(f"Unusable {what}: {problem}")


def _money(amount: float, currency: str) -> str:
    return f"{currency} {amount:,.2f}"


class NoticeDraftingError(Exception):
    """Raised when the LLM fails to draft usable notice text."""


class SlackDeliveryError(Exception):
    """Raised when Slack delivery fails, or Slack isn't configured."""


class NotificationResult(BaseModel):
    notice_text: str
    slack_channel: str
    slack_ts: str


def draft_margin_call_notice(
    counterparty_id: str,
    call_amount: float,
    currency: str,
    csa_terms: CSATerms,
    openai_client: OpenAI | None = None,
    settings: Settings | None = None,
    llm: LLMClient | None = None,
) -> str:
    settings = settings or get_settings()
    llm = llm or get_llm(settings, openai_client)

    request = (
        "Draft a margin call notice. Placeholders: {COUNTERPARTY} (the counterparty), "
        "{CALL_AMOUNT} (the margin call amount, with currency), {THRESHOLD} (the CSA "
        "threshold) and {MTA} (the CSA minimum transfer amount). {COUNTERPARTY} and "
        "{CALL_AMOUNT} must appear."
    )
    values = {
        "COUNTERPARTY": counterparty_id,
        "CALL_AMOUNT": _money(call_amount, currency),
        "THRESHOLD": _money(csa_terms.threshold, csa_terms.currency),
        "MTA": _money(csa_terms.mta, csa_terms.currency),
    }
    return _draft_with_placeholders(
        llm,
        request,
        values,
        {"COUNTERPARTY", "CALL_AMOUNT"},
        f"margin call notice for {counterparty_id}",
    )


def draft_sla_met_notice(
    counterparty_id: str,
    call_amount: float,
    currency: str,
    openai_client: OpenAI | None = None,
    settings: Settings | None = None,
    llm: LLMClient | None = None,
) -> str:
    """Confirms, in the same Slack channel as the original call notice, that
    the counterparty met its obligation within the SLA window. Before this,
    "SLA met" was only ever visible inside the app itself (trace/API) --
    found live by the user, who expected a Slack confirmation and never got
    one."""
    settings = settings or get_settings()
    llm = llm or get_llm(settings, openai_client)

    request = (
        "Draft a short confirmation that {COUNTERPARTY} met its margin call obligation "
        "of {CALL_AMOUNT} within the SLA window. This is a resolution confirmation, not "
        "a new call -- do not restate it as a demand. {COUNTERPARTY} and {CALL_AMOUNT} "
        "must appear."
    )
    values = {"COUNTERPARTY": counterparty_id, "CALL_AMOUNT": _money(call_amount, currency)}
    return _draft_with_placeholders(
        llm, request, values, set(values), f"SLA-met notice for {counterparty_id}"
    )


def send_slack_notice(
    text: str,
    settings: Settings | None = None,
    slack_client: WebClient | None = None,
) -> NotificationResult:
    settings = settings or get_settings()
    if not settings.slack_bot_token or not settings.slack_channel_id:
        raise SlackDeliveryError("SLACK_BOT_TOKEN/SLACK_CHANNEL_ID are not configured")

    slack_client = slack_client or WebClient(token=settings.slack_bot_token)
    try:
        response = slack_client.chat_postMessage(channel=settings.slack_channel_id, text=text)
    except SlackApiError as exc:
        raise SlackDeliveryError(f"Slack delivery failed: {exc.response['error']}") from exc

    return NotificationResult(
        notice_text=text,
        slack_channel=settings.slack_channel_id,
        slack_ts=str(response["ts"]),
    )
