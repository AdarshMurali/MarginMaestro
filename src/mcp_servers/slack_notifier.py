from mcp.server.fastmcp import FastMCP

from agents.communication import send_slack_notice

mcp = FastMCP("slack-notifier")


@mcp.tool()
def send_margin_call_notice(text: str) -> dict:
    """Send an already-drafted, already-approved margin call notice to the
    configured Slack channel. Never call before human approval."""
    return send_slack_notice(text).model_dump()


if __name__ == "__main__":
    mcp.run()
