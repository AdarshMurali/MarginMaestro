"""OpenTelemetry wiring (MM-92, Phase 9, docs/ARCHITECTURE.md's "Optional
OpenTelemetry traces" line). Deliberately just configuration -- library code
elsewhere (agents/orchestrator.py) calls `trace.get_tracer(__name__)` and
creates spans unconditionally, per OTel's own recommended pattern. Until
configure_tracing() is actually called, `get_tracer()` returns a no-op
tracer (spans are created but never recorded/exported, zero network calls)
-- so importing agents.orchestrator in a test never talks to a real Jaeger
instance unless something explicitly calls configure_tracing() first, which
only api/main.py's real app startup does."""

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter

from config.settings import Settings

_TRACES_PATH = "/v1/traces"

# Both the OTel SDK's own defaults (30s) -- tuned down so an unreachable
# collector (Jaeger not running -- true for every unit test, and a real
# possibility in production if it briefly restarts) fails fast instead of
# blocking. Found live: the default 30s export_timeout_millis added a real
# ~30s to the whole local test suite's teardown, once, when Jaeger wasn't
# running -- an API shouldn't hang that long on shutdown either just
# because its trace collector is briefly unreachable.
_EXPORT_REQUEST_TIMEOUT_SECONDS = 2.0
_EXPORT_TIMEOUT_MILLIS = 3_000


def configure_tracing(settings: Settings) -> None:
    """Sets the global TracerProvider, exporting to Jaeger's OTLP HTTP
    receiver via a background batching processor (non-blocking -- a
    request never waits on span export, and an unreachable collector just
    logs periodic warnings rather than failing anything). Idempotent in
    practice: OTel's API only honors the *first* set_tracer_provider() call
    per process and silently ignores later ones, so calling this more than
    once (e.g. multiple test files importing api.main) is harmless."""
    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: settings.otel_service_name}))
    exporter = _exporter(settings)
    if exporter is not None:
        provider.add_span_processor(
            BatchSpanProcessor(exporter, export_timeout_millis=_EXPORT_TIMEOUT_MILLIS)
        )
    # Without an exporter, spans are still created (log/trace correlation),
    # just not exported.
    trace.set_tracer_provider(provider)


TRACE_EXPORTERS = ("otlp", "cloudtrace", "none")


def _exporter(settings: Settings) -> SpanExporter | None:
    """TRACE_EXPORTER=otlp|cloudtrace|none (MM-127). otlp with an empty
    endpoint also means none (MM-123's switch)."""
    choice = settings.trace_exporter.strip().lower()
    if choice not in TRACE_EXPORTERS:
        raise ValueError(f"TRACE_EXPORTER must be one of {TRACE_EXPORTERS}, got {choice!r}")
    if choice == "cloudtrace":
        if not settings.gcp_project_id:
            raise ValueError("TRACE_EXPORTER=cloudtrace requires GCP_PROJECT_ID")
        from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter

        return CloudTraceSpanExporter(project_id=settings.gcp_project_id)
    if choice == "none" or not settings.otel_exporter_otlp_endpoint:
        return None
    return OTLPSpanExporter(
        endpoint=settings.otel_exporter_otlp_endpoint.rstrip("/") + _TRACES_PATH,
        timeout=_EXPORT_REQUEST_TIMEOUT_SECONDS,
    )


def flush_spans(timeout_millis: int = 2_000) -> None:
    """Export spans now (MM-127). On Cloud Run the CPU is only allocated
    while a request is being handled, so spans left in the batch queue at
    the end of a request could wait until the next one; the API calls this
    at the end of every request. Cheap when the queue is empty."""
    provider = trace.get_tracer_provider()
    force_flush = getattr(provider, "force_flush", None)
    if force_flush is not None:
        force_flush(timeout_millis)
