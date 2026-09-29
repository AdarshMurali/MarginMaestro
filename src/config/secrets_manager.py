import json
import os

from config.json_secret_source import JsonSecretSource

DEFAULT_AWS_REGION = "ap-south-1"


class SecretsManagerSource(JsonSecretSource):
    """Reads values from a single AWS Secrets Manager JSON secret,
    `marginmaestro/<app_env>` -- e.g. `marginmaestro/prod`."""

    def _fetch(self) -> dict[str, str]:
        import boto3

        region = os.environ.get("AWS_REGION", DEFAULT_AWS_REGION)
        client = boto3.client("secretsmanager", region_name=region)
        secret_id = f"marginmaestro/{self._app_env}"
        response = client.get_secret_value(SecretId=secret_id)
        values: dict[str, str] = json.loads(response["SecretString"])
        return values
