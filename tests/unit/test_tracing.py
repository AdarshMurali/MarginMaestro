from unittest.mock import patch

from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

from config.settings import Settings
from observability.tracing import configure_tracing


class TestConfigureTracing:
    def test_builds_the_exporter_endpoint_from_settings(self) -> None:
        settings = Settings(_env_file=None, otel_exporter_otlp_endpoint="http://jaeger:4318")

        with patch("observability.tracing.OTLPSpanExporter") as mock_exporter_cls:
            configure_tracing(settings)

        mock_exporter_cls.assert_called_once()
        _, kwargs = mock_exporter_cls.call_args
        assert kwargs["endpoint"] == "http://jaeger:4318/v1/traces"

    def test_strips_a_trailing_slash_before_appending_the_traces_path(self) -> None:
        settings = Settings(
            _env_file=None,
            otel_exporter_otlp_endpoint="http://jaeger:4318/",
            auth_backend_secret="x",
        )

        with patch("observability.tracing.OTLPSpanExporter") as mock_exporter_cls:
            configure_tracing(settings)

        _, kwargs = mock_exporter_cls.call_args
        assert kwargs["endpoint"] == "http://jaeger:4318/v1/traces"

    def test_real_exporter_construction_does_not_raise(self) -> None:
        """Not mocked here -- confirms the real OTLPSpanExporter class
        actually accepts the arguments configure_tracing() passes it
        (construction is local/instant, no network call happens)."""
        settings = Settings(_env_file=None, otel_exporter_otlp_endpoint="http://localhost:4318")
        configure_tracing(settings)  # no exception == pass
        assert OTLPSpanExporter is not None  # sanity: the real import worked
