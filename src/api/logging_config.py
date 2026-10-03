from collections.abc import MutableMapping
from typing import Any

import structlog
from opentelemetry import trace

from config.settings import get_settings


def cloud_logging_fields(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """MM-127: fields Cloud Logging understands in a JSON log line --
    `severity` (so ERROR lines are errors, not INFO) and, inside a span, the
    trace/span ids that link the line to its trace in Cloud Trace. Harmless
    locally: other tools just see two extra keys."""
    level = event_dict.get("level")
    if level:
        event_dict["severity"] = "WARNING" if level == "warn" else str(level).upper()
    context = trace.get_current_span().get_span_context()
    if context.is_valid:
        project = get_settings().gcp_project_id
        if project:
            event_dict["logging.googleapis.com/trace"] = (
                f"projects/{project}/traces/{context.trace_id:032x}"
            )
            event_dict["logging.googleapis.com/spanId"] = f"{context.span_id:016x}"
            event_dict["logging.googleapis.com/trace_sampled"] = context.trace_flags.sampled
    return event_dict


def configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.format_exc_info,
            cloud_logging_fields,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
