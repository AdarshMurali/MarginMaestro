"""Prometheus metrics for agent activity (MM-92, Phase 9). Scraped via
GET /metrics (api/main.py); visualized in the Grafana dashboard provisioned
under infra/grafana/dashboards/agent-activity.json."""

from collections.abc import Iterator
from contextlib import contextmanager
from time import perf_counter

from opentelemetry.trace import Tracer
from prometheus_client import Counter, Histogram

AGENT_STEP_TOTAL = Counter(
    "marginmaestro_agent_step_total",
    "Orchestrator lifecycle steps completed, by step and outcome",
    ["step", "outcome"],
)

AGENT_STEP_DURATION_SECONDS = Histogram(
    "marginmaestro_agent_step_duration_seconds",
    "Orchestrator lifecycle step duration in seconds, by step",
    ["step"],
)

MARGIN_CALL_BREACHES_TOTAL = Counter(
    "marginmaestro_margin_call_breaches_total",
    "Breach evaluations, by whether they actually breached",
    ["breached"],
)

MARGIN_CALL_APPROVAL_DECISIONS_TOTAL = Counter(
    "marginmaestro_margin_call_approval_decisions_total",
    "First-approver decisions, by decision",
    ["decision"],
)


@contextmanager
def observe_step(tracer: Tracer, step: str) -> Iterator[None]:
    """Wraps one orchestrator lifecycle step with both a trace span and
    Prometheus counters/duration -- the one place both signals are recorded
    together so every instrumented step gets the same treatment. An
    exception propagates unchanged after being recorded (both as an
    "error" outcome here and, via OTel's own context-manager behavior, as
    an exception event + ERROR status on the span) -- never swallowed."""
    start = perf_counter()
    with tracer.start_as_current_span(step):
        try:
            yield
        except Exception:
            AGENT_STEP_TOTAL.labels(step=step, outcome="error").inc()
            raise
        else:
            AGENT_STEP_TOTAL.labels(step=step, outcome="success").inc()
        finally:
            AGENT_STEP_DURATION_SECONDS.labels(step=step).observe(perf_counter() - start)
