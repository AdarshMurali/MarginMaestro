"""MM-130: the desk assistant's long-term memory -- what may be recalled,
how it reaches the model, and what Memory Bank is told to extract.
MM-131: the agent's own identity in the deploy config."""

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from google.adk.models import LlmRequest
from google.genai import types

from config.settings import Settings
from desk_assistant import deploy
from desk_assistant import memory as desk_memory

URLS = {
    "desk_mcp_market_data_url": "https://mcp-market-data-1.us-central1.run.app/mcp",
    "desk_mcp_rag_url": "https://mcp-rag-1.us-central1.run.app/mcp",
    "desk_mcp_margin_status_url": "https://mcp-margin-status-1.us-central1.run.app/mcp",
}


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **{**URLS, "gcp_project_id": "proj-x", **overrides})


# --- amount filter ----------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "CP-3 threshold is USD 90,000",
        "the call was $250k",
        "exposure 62957.76",
        "MTA 24000",
        "collateral of 1.2 million",
        "EUR 5 haircut",
        "3,718,825 was called",
    ],
)
def test_memories_with_amounts_are_dropped(text):
    assert desk_memory.has_amount(text)
    assert desk_memory.usable_memories([text]) == []


@pytest.mark.parametrize(
    "text",
    [
        "Analyst covers CP-2 and CP-3",
        "Prefers short answers with bullet points",
        "CP-6 disputes are usually about trade breaks",
        "Asked about HPE on 2026-10-02",
    ],
)
def test_qualitative_memories_are_kept(text):
    assert not desk_memory.has_amount(text)
    assert desk_memory.usable_memories([text, "  "]) == [text]


# --- recall -----------------------------------------------------------------------


def _memory(text: str) -> SimpleNamespace:
    return SimpleNamespace(content=types.Content(parts=[types.Part(text=text)]))


class FakeToolContext:
    def __init__(self, query: str | None, memories=None, fail: bool = False) -> None:
        self.user_content = (
            types.Content(role="user", parts=[types.Part(text=query)]) if query else None
        )
        self.memories = memories or []
        self.fail = fail
        self.query: str | None = None

    async def search_memory(self, query: str):
        if self.fail:
            raise RuntimeError("memory bank down")
        self.query = query
        return SimpleNamespace(memories=self.memories)


def _recall(context: FakeToolContext) -> LlmRequest:
    request = LlmRequest()
    asyncio.run(
        desk_memory.MemoryRecall().process_llm_request(tool_context=context, llm_request=request)
    )
    return request


def _instruction(request: LlmRequest) -> str:
    return str(request.config.system_instruction or "")


def test_recall_adds_filtered_memories_to_the_system_instruction():
    context = FakeToolContext(
        "any calls for me?",
        [_memory("Analyst covers CP-2 and CP-3"), _memory("CP-2 last call was USD 62,957")],
    )

    request = _recall(context)

    instruction = _instruction(request)
    assert "Analyst covers CP-2 and CP-3" in instruction
    assert "62,957" not in instruction
    assert "not a source of figures" in instruction
    assert context.query == "any calls for me?"
    assert not request.contents  # never injected as a user turn


def test_recall_without_a_message_or_memories_changes_nothing():
    assert _instruction(_recall(FakeToolContext(None))) == ""
    assert _instruction(_recall(FakeToolContext("hi", []))) == ""
    assert _instruction(_recall(FakeToolContext("hi", [_memory("USD 9,000")]))) == ""


def test_recall_failure_never_blocks_the_turn():
    assert _instruction(_recall(FakeToolContext("hi", fail=True))) == ""


# --- saving -----------------------------------------------------------------------


class FakeCallbackContext:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.saved = 0

    async def add_session_to_memory(self) -> None:
        if self.fail:
            raise ValueError("no memory service")
        self.saved += 1


def test_each_turn_is_saved_to_memory():
    context = FakeCallbackContext()

    asyncio.run(desk_memory.save_turn_to_memory(context))

    assert context.saved == 1


def test_a_save_failure_is_logged_not_raised(monkeypatch):
    errors: list[str] = []
    monkeypatch.setattr(desk_memory.logger, "error", lambda event, **kw: errors.append(event))

    asyncio.run(desk_memory.save_turn_to_memory(FakeCallbackContext(fail=True)))

    assert errors == ["desk_memory_save_failed"]


# --- what Memory Bank extracts, and the identity ---------------------------------


def test_memory_topics_are_qualitative_only():
    custom = [t["custom_memory_topic"] for t in deploy.MEMORY_TOPICS if "custom_memory_topic" in t]

    assert {t["label"] for t in custom} == {
        "analyst_coverage",
        "analyst_preferences",
        "counterparty_context",
    }
    assert all("Never amounts, prices" in t["description"] for t in custom)


def test_context_spec_sets_topics_ttl_and_extraction_model():
    spec = deploy.context_spec(_settings(desk_memory_model="gemini-test"))["memory_bank_config"]

    assert spec["customization_configs"][0]["memory_topics"] == deploy.MEMORY_TOPICS
    assert spec["ttl_config"] == {"default_ttl": "7776000s"}
    assert spec["generation_config"]["model"] == (
        "projects/proj-x/locations/global/publishers/google/models/gemini-test"
    )


def test_deploy_keeps_the_agent_on_its_service_account():
    """MM-131: Agent Identity broke Model Armor (mTLS-bound tokens, no
    regional mTLS endpoint), so the agent stays on mm-agent-sa."""
    config = deploy.deploy_config(_settings(), class_methods=[])

    assert config["identity_type"] == "SERVICE_ACCOUNT"
    assert config["service_account"] == "mm-agent-sa@proj-x.iam.gserviceaccount.com"
    assert "memory_bank_config" in config["context_spec"]


def test_deploy_config_is_valid_for_the_sdk():
    from vertexai._genai import types as vtypes

    config = vtypes.AgentEngineConfig(**deploy.deploy_config(_settings(), class_methods=[]))

    assert config.identity_type == vtypes.IdentityType.SERVICE_ACCOUNT
    assert config.context_spec.memory_bank_config.ttl_config.default_ttl == "7776000s"


# --- env file ---------------------------------------------------------------------


def test_env_file_sets_settings(tmp_path, monkeypatch):
    env = tmp_path / "deploy.env"
    env.write_text("# comment\n\nGCP_PROJECT_ID=proj-y\nDESK_MCP_AUTH = google\n", encoding="utf-8")
    monkeypatch.setenv("GCP_PROJECT_ID", "before")
    monkeypatch.setenv("DESK_MCP_AUTH", "before")

    deploy.load_env_file(env)

    assert os.environ["GCP_PROJECT_ID"] == "proj-y"
    assert os.environ["DESK_MCP_AUTH"] == "google"


@pytest.mark.parametrize(
    "line", ["SLACK_BOT_TOKEN=x", "OPENAI_API_KEY=x", "AUTH_BACKEND_SECRET=x", "NOT_A_PAIR"]
)
def test_env_file_refuses_secrets_and_bad_lines(tmp_path, line):
    env = tmp_path / "deploy.env"
    env.write_text(line + "\n", encoding="utf-8")

    with pytest.raises(ValueError):
        deploy.load_env_file(env)


def test_committed_prod_env_file_has_no_secrets():
    path = Path(deploy.__file__).with_name("deploy.prod.env")
    keys = [
        line.split("=", 1)[0]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]

    assert "GCP_PROJECT_ID" in keys
    assert "SECRETS_SOURCE" in keys  # a setting, allowed
    assert not any(deploy.SECRET_KEY.search(k) for k in keys)


def test_env_choice_loads_only_the_committed_file(monkeypatch):
    loaded = []
    monkeypatch.setattr(deploy, "load_env_file", lambda path: loaded.append(path))
    monkeypatch.setattr(deploy, "get_settings", lambda: (_ for _ in ()).throw(SystemExit(0)))
    monkeypatch.setattr(deploy.os, "chdir", lambda path: None)

    with pytest.raises(SystemExit):
        deploy.main(["--env", "prod"])
    with pytest.raises(SystemExit):
        deploy.main(["--env", "../../etc/passwd"])  # argparse rejects anything else

    assert loaded == [deploy.ENV_FILES["prod"]]


def test_memory_extraction_defaults_to_a_model_memory_bank_accepts():
    """Memory Bank rejected gemini-2.5-flash on the first redeploy."""
    spec = deploy.context_spec(_settings(gemini_model="gemini-2.5-flash"))
    model = spec["memory_bank_config"]["generation_config"]["model"]

    assert model == "projects/proj-x/locations/global/publishers/google/models/gemini-3.5-flash"
