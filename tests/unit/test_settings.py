from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

from config.parameter_store import ParameterStoreSource
from config.settings import Settings


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    from config.settings import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_defaults_when_nothing_set(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("APP_ENV", raising=False)
    settings = Settings(_env_file=None)
    assert settings.app_env == "local"
    assert settings.api_port == 8000
    assert settings.jira_project_key == "MM"
    assert settings.openai_api_key is None


def test_market_universe_list_parses_default() -> None:
    settings = Settings(_env_file=None)
    tickers = settings.market_universe_list
    assert len(tickers) == 30
    assert "AAPL" in tickers
    assert "SPCX" in tickers
    assert "BTC-USD" in tickers


def test_market_universe_list_parses_custom_value(monkeypatch) -> None:
    monkeypatch.setenv("MARKET_UNIVERSE", "AAPL, MSFT ,GOOGL")
    settings = Settings(_env_file=None)
    assert settings.market_universe_list == ["AAPL", "MSFT", "GOOGL"]


def test_env_vars_override_defaults(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("API_PORT", "9000")
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    settings = Settings(_env_file=None)
    assert settings.api_port == 9000
    assert settings.slack_bot_token == "xoxb-test"


def test_local_env_never_touches_aws(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "local")
    with patch("boto3.client") as mock_client:
        Settings(_env_file=None)
        mock_client.assert_not_called()


@mock_aws
def test_deployed_env_reads_from_parameter_store(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    ssm = boto3.client("ssm", region_name="ap-south-1")
    ssm.put_parameter(
        Name="/marginmaestro/dev/OPENAI_API_KEY",
        Value="sk-from-ssm",
        Type="SecureString",
    )
    ssm.put_parameter(
        Name="/marginmaestro/dev/MARGIN_CALL_SLA_MINUTES",
        Value="45",
        Type="String",
    )

    settings = Settings(_env_file=None)

    assert settings.openai_api_key == "sk-from-ssm"
    assert settings.margin_call_sla_minutes == 45


@mock_aws
def test_explicit_env_var_wins_over_parameter_store(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    ssm = boto3.client("ssm", region_name="ap-south-1")
    ssm.put_parameter(
        Name="/marginmaestro/dev/OPENAI_API_KEY",
        Value="sk-from-ssm",
        Type="SecureString",
    )

    settings = Settings(_env_file=None)

    assert settings.openai_api_key == "sk-from-env"


@mock_aws
def test_parameter_store_source_get_field_value() -> None:
    ssm = boto3.client("ssm", region_name="ap-south-1")
    ssm.put_parameter(
        Name="/marginmaestro/dev/OPENAI_API_KEY",
        Value="sk-direct",
        Type="SecureString",
    )
    source = ParameterStoreSource(Settings, "dev")
    field = Settings.model_fields["openai_api_key"]

    value, key, is_complex = source.get_field_value(field, "openai_api_key")

    assert value == "sk-direct"
    assert key == "OPENAI_API_KEY"
    assert is_complex is False


@mock_aws
def test_parameter_store_source_get_field_value_missing() -> None:
    source = ParameterStoreSource(Settings, "dev")
    field = Settings.model_fields["openai_api_key"]

    value, key, _ = source.get_field_value(field, "openai_api_key")

    assert value is None
    assert key == "openai_api_key"


def test_get_settings_is_cached(monkeypatch) -> None:
    from config.settings import get_settings

    monkeypatch.setenv("APP_ENV", "local")
    first = get_settings()
    second = get_settings()
    assert first is second
