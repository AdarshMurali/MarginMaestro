"""Agent Runtime entrypoint (MM-129): `desk_assistant.app:app`.

`AdkApp` gives the agent its query/session methods. Deployed on Agent
Runtime, it keeps conversations in Agent Platform Sessions (multi-turn chat
that survives scale-to-zero); run locally, it uses in-memory sessions.
"""

from vertexai.agent_engines import AdkApp

from desk_assistant.agent import build_agent

app = AdkApp(agent=build_agent(), app_name="margin_desk")
