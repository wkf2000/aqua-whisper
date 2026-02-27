"""Application-wide structlog configuration for JSON logging."""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from structlog.stdlib import add_logger_name
from opentelemetry.trace import get_current_span


def _add_trace_context(
    _logger: structlog.types.WrappedLogger,
    _method_name: str,
    event_dict: structlog.types.EventDict,
) -> structlog.types.EventDict:
    """Inject trace_id/span_id from the current OpenTelemetry span, if any."""
    try:
        span = get_current_span()
        span_context = span.get_span_context()
    except Exception:
        return event_dict

    if getattr(span_context, "trace_id", 0):
        event_dict["trace_id"] = f"{span_context.trace_id:032x}"
        event_dict["span_id"] = f"{span_context.span_id:016x}"
    return event_dict


def setup_logging(service_name: str, environment: str | None = None) -> None:
    """Configure structlog and stdlib logging for JSON output to stdout."""
    timestamper = structlog.processors.TimeStamper(fmt="iso")

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        add_logger_name,
        timestamper,
        _add_trace_context,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    structlog.configure(
        processors=shared_processors
        + [
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        stream=sys.stdout,
    )

    # Bind static context so every log line has these fields.
    logger = structlog.get_logger()
    bind_args: dict[str, Any] = {"service": service_name}
    if environment:
        bind_args["environment"] = environment
    logger.bind(**bind_args)

