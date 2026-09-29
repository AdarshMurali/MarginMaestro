import json
import sys
from types import SimpleNamespace
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

from config import gcp_secret_manager
from config.gcp_secret_manager import GcpSecretManagerSource
from config.secrets_manager import SecretsManagerSource
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
def test_deployed_env_reads_from_secrets_manager(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    sm = boto3.client("secretsmanager", region_name="ap-south-1")
    sm.create_secret(
        Name="marginmaestro/dev",
        SecretString=json.dumps(
            {"OPENAI_API_KEY": "sk-from-secrets-manager", "MARGIN_CALL_SLA_MINUTES": "45"}
        ),
    )

    settings = Settings(_env_file=None)

    assert settings.openai_api_key == "sk-from-secrets-manager"
    assert settings.margin_call_sla_minutes == 45


@mock_aws
def test_explicit_env_var_wins_over_secrets_manager(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    sm = boto3.client("secretsmanager", region_name="ap-south-1")
    sm.create_secret(
        Name="marginmaestro/dev",
        SecretString=json.dumps({"OPENAI_API_KEY": "sk-from-secrets-manager"}),
    )

    settings = Settings(_env_file=None)

    assert settings.openai_api_key == "sk-from-env"


@mock_aws
def test_secrets_manager_source_get_field_value() -> None:
    sm = boto3.client("secretsmanager", region_name="ap-south-1")
    sm.create_secret(
        Name="marginmaestro/dev",
        SecretString=json.dumps({"OPENAI_API_KEY": "sk-direct"}),
    )
    source = SecretsManagerSource(Settings, "dev")
    field = Settings.model_fields["openai_api_key"]

    value, key, is_complex = source.get_field_value(field, "openai_api_key")

    assert value == "sk-direct"
    assert key == "OPENAI_API_KEY"
    assert is_complex is False


@mock_aws
def test_secrets_manager_source_get_field_value_missing() -> None:
    sm = boto3.client("secretsmanager", region_name="ap-south-1")
    sm.create_secret(Name="marginmaestro/dev", SecretString=json.dumps({}))
    source = SecretsManagerSource(Settings, "dev")
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


# --- MM-101: SECRETS_SOURCE selection + GCP Secret Manager source ----------


class _FakeGcpClient:
    def __init__(self, secrets: dict[str, dict]) -> None:
        self._secrets = secrets
        self.requested: list[str] = []

    def access_secret_version(self, *, name: str):
        self.requested.append(name)
        body = json.dumps(self._secrets[name]).encode("utf-8")
        return SimpleNamespace(payload=SimpleNamespace(data=body))


_GCP_NAME = "projects/marginmaestro-demo/secrets/marginmaestro-prod/versions/latest"


@pytest.fixture
def fake_gcp(monkeypatch):
    client = _FakeGcpClient({_GCP_NAME: {"OPENAI_API_KEY": "sk-from-gcp", "API_PORT": "8080"}})
    monkeypatch.setattr(gcp_secret_manager, "_default_client", lambda: client)
    monkeypatch.setenv("GCP_PROJECT_ID", "marginmaestro-demo")
    return client


def test_gcp_source_reads_latest_version_of_env_secret(monkeypatch, fake_gcp) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("SECRETS_SOURCE", "gcp")

    settings = Settings(_env_file=None)

    assert settings.openai_api_key == "sk-from-gcp"
    assert settings.api_port == 8080
    assert fake_gcp.requested == [_GCP_NAME]


def test_env_var_wins_over_gcp_secret(monkeypatch, fake_gcp) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("SECRETS_SOURCE", "gcp")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")

    assert Settings(_env_file=None).openai_api_key == "sk-from-env"


def test_gcp_source_never_touches_aws(monkeypatch, fake_gcp) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("SECRETS_SOURCE", "gcp")
    with patch("boto3.client") as mock_client:
        Settings(_env_file=None)
        mock_client.assert_not_called()


def test_gcp_source_requires_project_id(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("SECRETS_SOURCE", "gcp")
    monkeypatch.delenv("GCP_PROJECT_ID", raising=False)

    with pytest.raises(ValueError, match="GCP_PROJECT_ID"):
        Settings(_env_file=None)


def test_gcp_source_get_field_value(fake_gcp) -> None:
    source = GcpSecretManagerSource(Settings, "prod", client_factory=lambda: fake_gcp)
    field = Settings.model_fields["openai_api_key"]

    assert source.get_field_value(field, "openai_api_key") == (
        "sk-from-gcp",
        "OPENAI_API_KEY",
        False,
    )


def test_secrets_source_env_skips_remote_even_when_deployed(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("SECRETS_SOURCE", "env")
    with patch("boto3.client") as mock_client:
        Settings(_env_file=None)
        mock_client.assert_not_called()


@mock_aws
def test_secrets_source_aws_is_explicitly_selectable(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("SECRETS_SOURCE", " AWS ")
    sm = boto3.client("secretsmanager", region_name="ap-south-1")
    sm.create_secret(Name="marginmaestro/dev", SecretString=json.dumps({"OPENAI_API_KEY": "sk-a"}))

    assert Settings(_env_file=None).openai_api_key == "sk-a"


def test_invalid_secrets_source_fails_loud(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("SECRETS_SOURCE", "vault")

    with pytest.raises(ValueError, match="SECRETS_SOURCE"):
        Settings(_env_file=None)


def test_default_client_builds_secret_manager_client(monkeypatch) -> None:
    fake_module = SimpleNamespace(SecretManagerServiceClient=lambda: "client")
    monkeypatch.setitem(sys.modules, "google.cloud.secretmanager", fake_module)
    import google.cloud

    monkeypatch.setattr(google.cloud, "secretmanager", fake_module, raising=False)

    assert gcp_secret_manager._default_client() == "client"
