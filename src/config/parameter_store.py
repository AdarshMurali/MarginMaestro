from typing import Any

from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings
from pydantic_settings.sources import PydanticBaseSettingsSource


class ParameterStoreSource(PydanticBaseSettingsSource):
    """Reads values from AWS SSM Parameter Store under /marginmaestro/<app_env>/."""

    def __init__(self, settings_cls: type[BaseSettings], app_env: str) -> None:
        super().__init__(settings_cls)
        self._app_env = app_env
        self._values: dict[str, str] | None = None

    def _load(self) -> dict[str, str]:
        if self._values is None:
            import boto3

            client = boto3.client("ssm")
            prefix = f"/marginmaestro/{self._app_env}/"
            values: dict[str, str] = {}
            paginator = client.get_paginator("get_parameters_by_path")
            for page in paginator.paginate(Path=prefix, WithDecryption=True, Recursive=True):
                for param in page["Parameters"]:
                    key = param["Name"].removeprefix(prefix)
                    values[key] = param["Value"]
            self._values = values
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
