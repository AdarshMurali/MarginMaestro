"""Deploys (or updates) the desk assistant on Agent Runtime (MM-129).

Run by a person, not CI -- it creates a billable resource:

    cd src
    ../.venv/Scripts/python.exe -m desk_assistant.deploy --env prod [--update <resource>]

`--env prod` loads deploy.prod.env, the committed non-secret settings
(project, MCP URLs from Terraform's `mcp_urls` output); without --update a
new agent is created. Deploys from source (no pickling, no staging bucket):
only the packages the agent imports are uploaded.

Cost settings (user rule: stay as close to $0 as possible):
min_instances=0 (no warm instance, cold starts accepted), max 2,
1 vCPU / 2 GiB -- inside Agent Runtime's 50 vCPU-h / 100 GiB-h monthly free tier.
"""

import argparse
import os
import re
from pathlib import Path
from typing import Any

from config.settings import Settings, get_settings

# Only what desk_assistant imports -- not the whole app (no OpenAI/Chroma/DB).
SOURCE_PACKAGES = [
    "desk_assistant",
    "config",
    "ports",
    "adapters/__init__.py",
    "adapters/selection.py",
    "adapters/guardrail_factory.py",
    "adapters/composite_guardrail.py",
    "adapters/incode_guardrail.py",
    "adapters/model_armor_guardrail.py",
]

# MM-130: what Memory Bank may extract from conversations. Qualitative only;
# amounts, prices and statuses change and must always come from the tools.
NO_FIGURES = " Never amounts, prices, thresholds, rates or call statuses."
MEMORY_TOPICS: list[dict[str, Any]] = [
    {
        "custom_memory_topic": {
            "label": "analyst_coverage",
            "description": "Which counterparties, tickers or books the analyst covers or "
            "follows, by name or id." + NO_FIGURES,
        }
    },
    {
        "custom_memory_topic": {
            "label": "analyst_preferences",
            "description": "How the analyst likes answers: format, level of detail, "
            "recurring questions." + NO_FIGURES,
        }
    },
    {
        "custom_memory_topic": {
            "label": "counterparty_context",
            "description": "Qualitative context the analyst shares about a counterparty, "
            "e.g. what its disputes are usually about or how its contact prefers to be "
            "reached." + NO_FIGURES,
        }
    },
    {"managed_memory_topic": {"managed_topic_enum": "EXPLICIT_INSTRUCTIONS"}},
]
MEMORY_TTL = f"{90 * 24 * 3600}s"  # 90 days: data minimisation


def context_spec(settings: Settings) -> dict[str, Any]:
    model = (
        f"projects/{settings.gcp_project_id}/locations/{settings.gcp_location}"
        f"/publishers/google/models/{settings.desk_memory_model}"
    )
    return {
        "memory_bank_config": {
            "customization_configs": [{"memory_topics": MEMORY_TOPICS}],
            "ttl_config": {"default_ttl": MEMORY_TTL},
            "generation_config": {"model": model},
        }
    }


# Committed settings files, by name: no path comes from the command line.
ENV_FILES = {"prod": Path(__file__).with_name("deploy.prod.env")}

# Env-file keys that name a secret (SECRETS_SOURCE is a setting, not one).
SECRET_KEY = re.compile(r"(TOKEN|SECRET|PASSWORD|API_KEY)$")

RUNTIME = {
    "min_instances": 0,
    "max_instances": 2,
    "resource_limits": {"cpu": "1", "memory": "2Gi"},
    "container_concurrency": 3,  # 2 * cpu + 1
}


def runtime_env(settings: Settings) -> dict[str, str]:
    """Environment of the deployed agent. No secrets: Vertex, Model Armor and
    the MCP services all authenticate as the agent's identity."""
    return {
        "APP_ENV": settings.app_env,
        "SECRETS_SOURCE": "env",
        "GOOGLE_GENAI_USE_VERTEXAI": "TRUE",
        "GCP_PROJECT_ID": settings.gcp_project_id or "",
        "GCP_LOCATION": settings.gcp_location,
        "GEMINI_MODEL": settings.gemini_model,
        "GUARDRAIL_PROVIDER": settings.guardrail_provider,
        "MODEL_ARMOR_LOCATION": settings.model_armor_location,
        "MODEL_ARMOR_TEMPLATE_ID": settings.model_armor_template_id,
        "DESK_MCP_MARKET_DATA_URL": settings.desk_mcp_market_data_url,
        "DESK_MCP_RAG_URL": settings.desk_mcp_rag_url,
        "DESK_MCP_MARGIN_STATUS_URL": settings.desk_mcp_margin_status_url,
        "DESK_MCP_AUTH": "google",
    }


def deploy_config(settings: Settings, class_methods: list[dict[str, Any]]) -> dict[str, Any]:
    if not settings.gcp_project_id:
        raise ValueError("GCP_PROJECT_ID is required to deploy")
    return {
        "display_name": "margin-desk-assistant",
        "description": "MarginMaestro 'Ask the margin desk' (ADK, read-only MCP tools)",
        "source_packages": SOURCE_PACKAGES,
        "entrypoint_module": "desk_assistant.app",
        "entrypoint_object": "app",
        "requirements_file": "desk_assistant/requirements.txt",
        "agent_framework": "google-adk",
        "class_methods": class_methods,
        # MM-131: the agent runs as its own Agent Identity principal, not a
        # shared service account; "" clears the old mm-agent-sa on update.
        "identity_type": "AGENT_IDENTITY",
        "service_account": "",
        "env_vars": runtime_env(settings),
        "context_spec": context_spec(settings),
        **RUNTIME,
    }


def load_env_file(path: Path) -> None:
    """Sets KEY=VALUE lines as environment variables (comments and blanks
    skipped). For non-secret deploy settings only; it refuses obvious secrets."""
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep:
            raise ValueError(f"Not KEY=VALUE: {line!r}")
        key = key.strip()
        if SECRET_KEY.search(key.upper()):
            raise ValueError(f"{key} looks like a secret; deploy env files hold settings only")
        os.environ[key] = value.strip()
    get_settings.cache_clear()


def _class_methods(app: Any) -> list[dict[str, Any]]:
    """The query/session methods AdkApp registers, as the API expects them.
    The SDK derives these itself only for pickled deploys; a source deploy
    must pass them (helper from the pinned google-cloud-aiplatform)."""
    from vertexai._genai import _agent_engines_utils as utils

    specs = utils._generate_class_methods_spec_or_raise(
        agent=app, operations=utils._get_registered_operations(agent=app)
    )
    return [utils._to_dict(spec) for spec in specs]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", metavar="RESOURCE", help="existing reasoningEngines/... name")
    parser.add_argument(
        "--env",
        choices=sorted(ENV_FILES),
        help="load the committed, non-secret settings file for this environment",
    )
    args = parser.parse_args(argv)
    if args.env:
        load_env_file(ENV_FILES[args.env])

    src = Path(__file__).resolve().parents[1]
    os.chdir(src)  # source_packages are relative to src/
    settings = get_settings()

    import vertexai

    from desk_assistant.app import app

    config = deploy_config(settings, _class_methods(app))
    client = vertexai.Client(project=settings.gcp_project_id, location=settings.gcp_location)
    if args.update:
        engine = client.agent_engines.update(name=args.update, config=config)
    else:
        engine = client.agent_engines.create(config=config)
    print(f"DESK_AGENT_RESOURCE={engine.api_resource.name}")


if __name__ == "__main__":
    main()
