"""'Ask the margin desk' (MM-129): an ADK agent on Agent Runtime that answers
analysts' questions by choosing tools from the read-only MCP servers.

Unlike the margin-call orchestrator (a fixed LangGraph pipeline on Cloud
Run), this agent decides at runtime which tools to call. It can read
prices, CSA/policy documents and margin-call status, scoped to the analyst,
and nothing else: it has no tool that changes state or contacts a client.
"""
