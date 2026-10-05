"""Deploys (or updates) the desk assistant on Agent Runtime (MM-129).

Run by a person, not CI -- it creates a billable resource:

    cd src
    python -m desk_assistant.deploy                       # create
    python -m desk_assistant.deploy --update <resource>   # new revision

Reads the MCP URLs from the environment (DESK_MCP_*_URL, i.e. Terraform's
`mcp_urls` output). Deploys from source (no pickling, no staging bucket):
only the packages the agent imports are uploaded.

Cost settings (user rule: stay as close to $0 as possible):
min_instances=0 (no warm instance, cold starts accepted), max 2,
1 vCPU / 2 GiB -- inside Agent Runtime's 50 vCPU-h / 100 GiB-h monthly free tier.
"""

import argparse
import os
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
        "service_account": f"mm-agent-sa@{settings.gcp_project_id}.iam.gserviceaccount.com",
        "env_vars": runtime_env(settings),
        **RUNTIME,
    }


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
    args = parser.parse_args(argv)

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
