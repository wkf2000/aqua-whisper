"""Celery app configuration."""

from celery import Celery

from app.config import settings
from app.logging_config import setup_logging
from app.tracing import setup_tracing

celery_app = Celery(
    "aqua_whisper",
    broker=settings.REDIS_URL,
    # No result_backend: webhook-only design, no GET /tasks.
    broker_connection_retry_on_startup=True,
    broker_connection_retry=True,
)


setup_logging(service_name="aqua-whisper-worker", environment=settings.ENV)
setup_tracing(service_name="aqua-whisper-worker", environment=settings.ENV)

celery_app.autodiscover_tasks(["app"])
