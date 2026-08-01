"""Communication Agent (MM-41, docs/AGENTS.md #6): drafts the client-facing
margin-call notice via the LLM, then -- only after human approval -- sends it
through Slack. Never sends before the approval gate. Message content is
drafted by the LLM; the send itself is deterministic code (CLAUDE.md golden
rule 1 -- the LLM never computes or alters a figure, only phrases the notice
around numbers it's given)."""

from openai import OpenAI
from pydantic import BaseModel
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from calc.models import CSATerms
from config.settings import Settings, get_settings

SYSTEM_PROMPT = (
    "You draft formal, concise client-facing margin call notices for a bank "
    "operations team. Use only the figures given in the request -- never "
    "invent, estimate, or recompute any number. 1-2 short professional "
    "paragraphs, no markdown, no subject line (this is posted directly to a "
    "chat channel, not emailed)."
)


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
) -> str:
    settings = settings or get_settings()
    openai_client = openai_client or OpenAI(api_key=settings.openai_api_key)

    prompt = (
        f"Counterparty: {counterparty_id}\n"
        f"Margin call amount: {call_amount:,.2f} {currency}\n"
        f"CSA threshold: {csa_terms.threshold:,.2f} {csa_terms.currency}\n"
        f"CSA minimum transfer amount: {csa_terms.mta:,.2f} {csa_terms.currency}\n\n"
        "Draft the margin call notice using exactly these figures."
    )
    completion = openai_client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    )
    text = completion.choices[0].message.content
    if not text or not text.strip():
        raise NoticeDraftingError(f"LLM returned an empty margin call notice for {counterparty_id}")
    return text.strip()


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
