"""OpenTelemetry tracing configuration for the application."""

from __future__ import annotations

from typing import Optional

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.config import settings

_TRACING_CONFIGURED = False


def setup_tracing(service_name: str, environment: Optional[str] = None) -> None:
    """Configure a global TracerProvider with OTLP exporter to OpenObserve."""
    global _TRACING_CONFIGURED
    if _TRACING_CONFIGURED:
        return

    resource_attrs = {
        "service.name": service_name,
    }
    if environment:
        resource_attrs["deployment.environment"] = environment

    resource = Resource.create(resource_attrs)
    provider = TracerProvider(resource=resource)

    endpoint = getattr(settings, "OTEL_EXPORTER_OTLP_ENDPOINT", None)
    if endpoint:
        exporter = OTLPSpanExporter(endpoint=endpoint)
        span_processor = BatchSpanProcessor(exporter)
        provider.add_span_processor(span_processor)

    trace.set_tracer_provider(provider)

    _TRACING_CONFIGURED = True

