from abc import abstractmethod
from typing import Any

from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings
from pydantic_settings.sources import PydanticBaseSettingsSource


class JsonSecretSource(PydanticBaseSettingsSource):
    """Base for settings sources backed by one JSON secret per environment
    (AWS Secrets Manager `marginmaestro/<app_env>`, GCP Secret Manager
    `marginmaestro-<app_env>`). Keys in the secret's JSON body are matched
    against Settings fields by uppercased field name (or explicit alias).
    The secret is fetched once, lazily, on first use."""

    def __init__(self, settings_cls: type[BaseSettings], app_env: str) -> None:
        super().__init__(settings_cls)
        self._app_env = app_env
        self._values: dict[str, str] | None = None

    @abstractmethod
    def _fetch(self) -> dict[str, str]:
        """Return the secret's JSON body. Must fail loud if it can't be read."""

    def _load(self) -> dict[str, str]:
        if self._values is None:
            self._values = self._fetch()
        return self._values

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        key = field.alias or field_name.upper()
        values = self._load()
        if key in values:
            return values[key], key, False
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        values = self._load()
        result: dict[str, Any] = {}
        for field_name, field in self.settings_cls.model_fields.items():
            key = field.alias or field_name.upper()
            if key in values:
                result[field_name] = values[key]
        return result
