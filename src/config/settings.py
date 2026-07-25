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

    llm_provider: str = "ollama"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"

    embeddings_provider: str = "local"
    embeddings_model: str = "BAAI/bge-small-en-v1.5"

    chroma_persist_dir: str = "./chroma_db"

    db_host: str | None = None
    db_port: int = 1433
    db_name: str = "marginmaestro"
    db_user: str | None = None
    db_password: str | None = None

    kafka_bootstrap_servers: str = "localhost:19092"
    kafka_topic_prices: str = "market.prices"
    kafka_topic_events: str = "market.events"
    kafka_topic_calls: str = "margin.calls"

    market_feed_mode: str = "simulated"
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
