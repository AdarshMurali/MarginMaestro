import os
from functools import lru_cache

from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from config.parameter_store import ParameterStoreSource


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

    llm_provider: str = "ollama"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"

    chroma_host: str = "localhost"
    chroma_port: int = 8100

    db_host: str | None = None
    db_port: int = 1433
    db_name: str = "marginmaestro"
    db_user: str | None = None
    db_password: str | None = None

    kafka_bootstrap_servers: str = "localhost:19092"
    kafka_topic_prices: str = "market.prices"
    kafka_topic_events: str = "market.events"
    kafka_topic_impact: str = "market.impact"
    kafka_topic_calls: str = "margin.calls"

    fred_api_key: str | None = None

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
    # Seed-time only (persistence/seed_users.py hashes these into `users`
    # once) -- never read at request time, so rotating them doesn't
    # invalidate already-seeded accounts. Documented local-dev defaults, not
    # real secrets; change before any non-demo deployment.
    demo_approver_password: str = "MarginMaestro!Approver1"
    demo_viewer_password: str = "MarginMaestro!Viewer1"
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
        if app_env == "local":
            return init_settings, env_settings, dotenv_settings, file_secret_settings
        return (
            init_settings,
            env_settings,
            ParameterStoreSource(settings_cls, app_env),
            dotenv_settings,
            file_secret_settings,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
