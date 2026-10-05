"""Long-term memory for the desk assistant (MM-130): Agent Platform Memory
Bank, scoped per analyst.

- **What is remembered** is set where memories are extracted (deploy.py,
  MEMORY_TOPICS): who covers what, how they like answers, qualitative context
  about counterparties. Never amounts, prices or statuses -- those change and
  must come from the tools (golden rule 1).
- **Recall** (`MemoryRecall`): before each model call, memories relevant to
  the analyst's message are looked up and added to the system instruction as
  context. Any memory that contains an amount is dropped here in code, so a
  stale figure can't reach the model even if extraction let one through.
- **Saving** (`save_turn_to_memory`): after each turn the session is sent to
  Memory Bank, which extracts memories in the background.

Locally ADK uses an in-memory store; deployed, AdkApp uses Memory Bank.
"""

import re
from typing import Any

import structlog
from google.adk.models import LlmRequest
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext

logger = structlog.get_logger()

# Currency amounts and long or decimal numbers ("USD 90,000", "$1.2m",
# "62957.76", "250k"). Counterparty ids like "CP-3" and dates stay allowed.
AMOUNT_PATTERN = re.compile(
    r"(?:[$€£]|\b(?:usd|eur|gbp|inr)\b)\s*\d"
    r"|\b\d[\d,]*\.\d+\b"
    r"|\b\d{1,3}(?:,\d{3})+\b"
    r"|\b\d{4,}\b(?!-\d)"
    r"|\b\d+(?:\.\d+)?\s*(?:k|m|bn|million|billion)\b",
    re.IGNORECASE,
)

RECALL_HEADER = (
    "What you remember about this analyst from earlier conversations. Use it "
    "only as context (coverage, preferences). It is not a source of figures "
    "or statuses: always get those from the tools."
)


def has_amount(text: str) -> bool:
    return AMOUNT_PATTERN.search(text) is not None


def usable_memories(texts: list[str]) -> list[str]:
    """Memories safe to show the model: non-empty and free of amounts."""
    kept = [text.strip() for text in texts if text.strip() and not has_amount(text)]
    dropped = len([t for t in texts if t.strip()]) - len(kept)
    if dropped:
        logger.warning("desk_memory_dropped", count=dropped, reason="contains_amount")
    return kept


class MemoryRecall(BaseTool):  # type: ignore[misc]
    """Like ADK's PreloadMemoryTool, but filtered and added to the system
    instruction instead of as a user turn: the guardrail screens the
    analyst's own words, and memory text must never be mistaken for them."""

    def __init__(self) -> None:
        super().__init__(name="memory_recall", description="memory_recall")

    async def process_llm_request(
        self, *, tool_context: ToolContext, llm_request: LlmRequest
    ) -> None:
        content = tool_context.user_content
        query = " ".join(p.text for p in (content.parts if content else None) or [] if p.text)
        if not query:
            return
        try:
            response = await tool_context.search_memory(query)
        except Exception as exc:  # noqa: BLE001 -- recall is best effort, never blocks a turn
            logger.warning("desk_memory_recall_failed", error=type(exc).__name__)
            return
        texts = [
            " ".join(part.text for part in (memory.content.parts or []) if part.text)
            for memory in response.memories
        ]
        memories = usable_memories(texts)
        if memories:
            llm_request.append_instructions(
                [RECALL_HEADER + "\n" + "\n".join(f"- {m}" for m in memories)]
            )


async def save_turn_to_memory(callback_context: Any) -> None:
    """after_agent_callback: hand the session to Memory Bank for extraction.
    A failure is logged loudly but doesn't fail the analyst's answer, which
    has already been produced and screened."""
    try:
        await callback_context.add_session_to_memory()
    except Exception as exc:  # noqa: BLE001
        logger.error("desk_memory_save_failed", error=type(exc).__name__, detail=str(exc)[:200])
