import json
import os
from collections.abc import Callable
from typing import Any

from pydantic_settings import BaseSettings

from config.json_secret_source import JsonSecretSource


def _default_client() -> Any:
    # Imported lazily: the GCP client library is only needed when
    # SECRETS_SOURCE=gcp, so AWS and local runs never load it.
    from google.cloud import secretmanager

    return secretmanager.SecretManagerServiceClient()


class GcpSecretManagerSource(JsonSecretSource):
    """Reads values from a single GCP Secret Manager JSON secret,
    `marginmaestro-<app_env>` (GCP secret IDs can't contain `/`), latest
    version, in the project named by the GCP_PROJECT_ID env var. Auth is the
    runtime's Application Default Credentials (the Cloud Run service account
    in GCP, `gcloud auth application-default login` locally)."""

    def __init__(
        self,
        settings_cls: type[BaseSettings],
        app_env: str,
        client_factory: Callable[[], Any] | None = None,
    ) -> None:
        super().__init__(settings_cls, app_env)
        self._client_factory = client_factory

    def _fetch(self) -> dict[str, str]:
        project_id = os.environ.get("GCP_PROJECT_ID")
        if not project_id:
            raise ValueError("SECRETS_SOURCE=gcp requires the GCP_PROJECT_ID environment variable")
        name = f"projects/{project_id}/secrets/marginmaestro-{self._app_env}/versions/latest"
        # Resolved at call time (not as a default argument) so tests can
        # swap the module-level factory and never reach real GCP.
        factory = self._client_factory or _default_client
        response = factory().access_secret_version(name=name)
        values: dict[str, str] = json.loads(response.payload.data.decode("utf-8"))
        return values
