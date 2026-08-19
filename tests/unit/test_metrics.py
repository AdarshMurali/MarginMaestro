import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from observability.metrics import AGENT_STEP_DURATION_SECONDS, AGENT_STEP_TOTAL, observe_step


@pytest.fixture
def traced():
    """A real TracerProvider backed by an in-memory exporter -- spans are
    genuinely created and recorded, just captured locally instead of sent
    over the network, so tests can assert on them directly."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return trace.get_tracer("test", tracer_provider=provider), exporter


def _counter_value(step: str, outcome: str) -> float:
    return AGENT_STEP_TOTAL.labels(step=step, outcome=outcome)._value.get()


def _duration_count(step: str) -> float:
    return AGENT_STEP_DURATION_SECONDS.labels(step=step)._sum.get()


class TestObserveStep:
    def test_success_increments_the_success_counter_and_creates_a_span(self, traced) -> None:
        tracer, exporter = traced
        before = _counter_value("unit-test-step-a", "success")

        with observe_step(tracer, "unit-test-step-a"):
            pass

        assert _counter_value("unit-test-step-a", "success") == before + 1
        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].name == "unit-test-step-a"
        assert spans[0].status.is_ok

    def test_records_duration(self, traced) -> None:
        tracer, _ = traced
        before = _duration_count("unit-test-step-duration")

        with observe_step(tracer, "unit-test-step-duration"):
            pass

        assert _duration_count("unit-test-step-duration") >= before

    def test_exception_increments_the_error_counter_and_propagates(self, traced) -> None:
        tracer, exporter = traced
        before = _counter_value("unit-test-step-b", "error")

        with pytest.raises(ValueError, match="boom"), observe_step(tracer, "unit-test-step-b"):
            raise ValueError("boom")

        assert _counter_value("unit-test-step-b", "error") == before + 1
        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        assert not spans[0].status.is_ok
