from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from agents.communication import send_slack_notice

mcp = FastMCP("slack-notifier")


@mcp.tool()
def send_margin_call_notice(
    text: Annotated[str, Field(description="The already-drafted margin call notice text to send.")],
) -> dict:
    """Send an already-drafted, already-approved margin call notice to the
    configured Slack channel. Never call before human approval. Raises
    SlackDeliveryError if SLACK_BOT_TOKEN/SLACK_CHANNEL_ID aren't
    configured, or if the Slack API call itself fails.
    """
    return send_slack_notice(text).model_dump()


if __name__ == "__main__":
    mcp.run()
