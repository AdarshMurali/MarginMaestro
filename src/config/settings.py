import os
from functools import lru_cache

from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from config.gcp_secret_manager import GcpSecretManagerSource
from config.secrets_manager import SecretsManagerSource


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "local"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_allowed_origins: str = "http://localhost:3000"

    @property
    def cors_allowed_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]

    # MM-128: Host headers the MCP servers accept over HTTP (DNS-rebinding
    # protection stays on). Locally any port on localhost; on Cloud Run the
    # service's own deterministic hostname, set by Terraform.
    mcp_allowed_hosts: str = "localhost:*,127.0.0.1:*"

    @property
    def mcp_allowed_hosts_list(self) -> list[str]:
        return [host.strip() for host in self.mcp_allowed_hosts.split(",") if host.strip()]

    # MM-109: openai (default -- the pre-GCP stack, AWS unchanged) or vertex
    # (Gemini on Vertex AI). The old "ollama" default was never honoured by
    # the agents, which always used OpenAI.
    llm_provider: str = "openai"
    # MM-113: screens every LLM call. incode (default: conservative, no
    # network, post-trial fallback) | modelarmor (MM-114) | none (local only).
    guardrail_provider: str = "incode"
    # MM-114: Model Armor template (regional) used when GUARDRAIL_PROVIDER=modelarmor.
    model_armor_template_id: str = "marginmaestro-llm-traffic"
    model_armor_location: str = "us-central1"
    # MM-115: masks personal/account data before the model and the RAG index.
    # regex (default: strict, no network, post-trial fallback) | sdp
    # (Sensitive Data Protection, us-central1) | none (local only).
    redactor_provider: str = "regex"
    # MM-117: cost / loop bounds. Per run: <= max_agent_steps graph steps, each
    # LLM call <= llm_max_prompt_chars in and llm_max_output_tokens out.
    max_agent_steps: int = 25
    llm_max_prompt_chars: int = 60_000
    llm_max_output_tokens: int = 4096
    # Per-user limit on the action endpoints (approve/respond/simulate...).
    rate_limit_per_minute: int = 20
    sdp_location: str = "us-central1"
    # Pinned model version, never an alias (ADR-0009). MM-117 switched from
    # gemini-3.8-flash @ global to gemini-2.5-flash @ us-central1: the global
    # endpoint stalled randomly for 60-90 s (it broke the full demo), the
    # regional one is steady, keeps data in-region, and scores 8/8 on the
    # golden regression. Gemini 3.x is served only from `global`.
    gemini_model: str = "gemini-2.5-flash"
    gemini_location: str = "us-central1"

    # MM-129: "Ask the margin desk" (ADK agent on Agent Runtime). The API
    # talks to it when DESK_ASSISTANT=agent_runtime; "none" turns chat off.
    desk_assistant: str = "none"
    # projects/<p>/locations/<l>/reasoningEngines/<id>, printed by the deploy script.
    desk_agent_resource: str = ""
    # The agent's MCP endpoints (Terraform output mcp_urls) and how it signs
    # calls to them: "google" = an ID token per service (Cloud Run IAM),
    # "none" = local servers.
    desk_mcp_market_data_url: str = ""
    desk_mcp_rag_url: str = ""
    desk_mcp_margin_status_url: str = ""
    desk_mcp_auth: str = "none"
    # Gemini 3.x: thinking level (low | high); Gemini 2.5: thinking budget in
    # tokens (0 = off). Extraction/drafting don't need thinking. "" / None =
    # the model default.
    gemini_thinking_level: str = ""
    gemini_thinking_budget: int | None = 0
    # Shared by Vertex AI and (as GCP_PROJECT_ID) the Secret Manager source.
    gcp_project_id: str | None = None
    gcp_location: str = "us-central1"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"

    # MM-102: which adapter backs each port (adapters/factory.py). Defaults are
    # the pre-GCP stack; each GCP phase adds its value (pgvector, pubsub, whatsapp).
    vector_store: str = "chroma"  # chroma | pgvector (MM-110, needs DB_DIALECT=postgres)
    # MM-110: openai (text-embedding-3-small, with Chroma) or vertex
    # (gemini-embedding-001 at 768 dims, required by pgvector's vector(768)).
    embedding_provider: str = "openai"
    gemini_embedding_model: str = "gemini-embedding-001"
    # Embeddings are served in us-central1, so the corpus stays in-region
    # (unlike Gemini 3.x chat, which is global-only).
    gemini_embedding_location: str = "us-central1"
    embedding_dimensions: int = 768
    event_bus: str = "kafka"  # kafka | pubsub (MM-119; same topic names)
    client_notifier: str = "slack"
    # MM-122: SLA timers. none = no timer (the check is called by hand);
    # cloudtasks = one Cloud Tasks task per call, at its deadline, calling
    # {internal_base_url}/internal/sla/{thread_id}/check as the invoker SA.
    sla_scheduler: str = "none"
    cloud_tasks_location: str = "us-central1"
    cloud_tasks_queue: str = "sla-checks"
    internal_base_url: str | None = None

    chroma_host: str = "localhost"
    chroma_port: int = 8100

    # Phase 9 (MM-92): Jaeger's OTLP HTTP receiver default port. "/v1/traces"
    # is appended by tracing.configure_tracing(), not stored here, so this
    # value doubles as the base for any future OTLP signal (metrics/logs).
    otel_exporter_otlp_endpoint: str = "http://localhost:4318"
    # MM-127: where spans go. otlp = Jaeger locally (endpoint above);
    # cloudtrace = Google Cloud Trace (needs GCP_PROJECT_ID); none = no export.
    trace_exporter: str = "otlp"
    otel_service_name: str = "marginmaestro-api"

    # MM-104: mssql (Azure SQL / local SQL Edge, the AWS default) or postgres
    # (local pgvector container, CI, Cloud SQL). DB_PORT must match: 1433 / 5432.
    db_dialect: str = "mssql"
    db_host: str | None = None
    db_port: int = 1433
    db_name: str = "marginmaestro"
    db_user: str | None = None
    db_password: str | None = None
    # MM-123: password (default) or iam -- Cloud SQL IAM database login, the
    # runtime service account's OAuth token as the password (Postgres only).
    # A DB_HOST starting with '/' is a Unix socket directory, e.g. Cloud Run's
    # /cloudsql/<project>:<region>:<instance>.
    db_auth: str = "password"

    kafka_bootstrap_servers: str = "localhost:19092"
    kafka_topic_prices: str = "market.prices"
    kafka_topic_events: str = "market.events"
    kafka_topic_impact: str = "market.impact"
    kafka_topic_calls: str = "margin.calls"
    # MM-93: where the Event Agent's consumer loop routes a message after
    # exhausting its retry budget, instead of crash-looping forever on one
    # poison message (see streaming/event_agent.py's _handle_with_retry).
    kafka_topic_dead_letter: str = "market.dead-letter"

    fred_api_key: str | None = None

    # MM-111: where RAG source documents live -- s3 (AWS, default) or gcs.
    document_store: str = "s3"
    gcs_documents_bucket: str | None = None
    s3_documents_bucket: str | None = None
    s3_documents_bucket_owner: str | None = None

    market_feed_mode: str = "simulated"
    # MM-59: fixed-interval poll, deliberately no volatility-threshold logic.
    # The curated universe below (~30 tickers) is batched into one
    # yf.Tickers(...) call, so 60s balances "never stale for more than ~1
    # min" against free-tier yfinance rate-limit risk.
    live_feed_poll_interval_seconds: int = 60
    market_universe: str = (
        "AAPL,MSFT,GOOGL,AMZN,TSLA,NVDA,META,HPE,JPM,WFC,SPCX,"
        "PLTR,AMD,MU,SMCI,NFLX,INTC,"
        "SPY,XOM,JNJ,BRK-B,V,DIS,"
        "IEF,TLT,SHY,"
        "BTC-USD,ETH-USD,SOL-USD,XRP-USD"
    )

    @property
    def market_universe_list(self) -> list[str]:
        return [ticker.strip() for ticker in self.market_universe.split(",") if ticker.strip()]

    slack_bot_token: str | None = None
    slack_channel_id: str | None = None

    jira_base_url: str | None = None
    jira_email: str | None = None
    jira_api_token: str | None = None
    jira_project_key: str = "MM"

    margin_call_sla_minutes: int = 60

    servicenow_instance_url: str | None = None
    servicenow_username: str | None = None
    servicenow_password: str | None = None

    # MM-57: shared secret for the short-lived JWT the frontend's NextAuth
    # session mints and this backend verifies on mutating endpoints -- a
    # separate secret from NextAuth's own internal session-cookie
    # encryption key (NEXTAUTH_SECRET), which this backend never sees.
    auth_backend_secret: str | None = None
    # MM-120/121: who may call the internal endpoints (/internal/prices/refresh,
    # /internal/pubsub/push). Either the shared job token (local runs), or a
    # Google-signed OIDC token for `internal_caller_service_account` with this
    # audience (Cloud Scheduler and Pub/Sub push, from G5). Neither set = the
    # endpoints are disabled (503).
    internal_job_token: str | None = None
    internal_caller_audience: str | None = None
    internal_caller_service_account: str | None = None
    # Seed-time only (persistence/seed_users.py hashes these into `users`
    # once) -- never read at request time, so rotating them doesn't
    # invalidate already-seeded accounts. Documented local-dev defaults, not
    # real secrets; change before any non-demo deployment.
    demo_approver_password: str = "MarginMaestro!Approver1"
    # MM-106: margin analysts (read-only, own book only) and the auditor
    # (read-only, firm-wide) replace the single `viewer` account.
    demo_analyst_password: str = "MarginMaestro!Analyst1"
    demo_auditor_password: str = "MarginMaestro!Auditor1"
    demo_manager_password: str = "MarginMaestro!Manager1"

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        app_env = os.environ.get("APP_ENV", "local")
        secrets_source = _secrets_source(app_env)
        if secrets_source == "env":
            return init_settings, env_settings, dotenv_settings, file_secret_settings
        remote: PydanticBaseSettingsSource
        if secrets_source == "gcp":
            remote = GcpSecretManagerSource(settings_cls, app_env)
        else:
            remote = SecretsManagerSource(settings_cls, app_env)
        # Explicit env vars always win over the remote secret.
        return init_settings, env_settings, remote, dotenv_settings, file_secret_settings


_SECRETS_SOURCES = ("env", "aws", "gcp")


def _secrets_source(app_env: str) -> str:
    """MM-101: which store deployed secrets come from. SECRETS_SOURCE picks it
    explicitly; unset keeps the pre-GCP behaviour (env only when
    APP_ENV=local, AWS Secrets Manager otherwise), so the AWS deployment
    needs no config change (ground rule 6, docs/gcp/GCP_ROADMAP.md)."""
    explicit = os.environ.get("SECRETS_SOURCE")
    if explicit is None:
        return "env" if app_env == "local" else "aws"
    source = explicit.strip().lower()
    if source not in _SECRETS_SOURCES:
        raise ValueError(f"SECRETS_SOURCE must be one of {_SECRETS_SOURCES}, got {explicit!r}")
    return source


@lru_cache
def get_settings() -> Settings:
    return Settings()
