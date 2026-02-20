"""Celery app configuration."""

from celery import Celery

from app.config import settings

celery_app = Celery(
    "aqua_whisper",
    broker=settings.REDIS_URL,
    # No result_backend: webhook-only design, no GET /tasks.
    broker_connection_retry_on_startup=True,
    broker_connection_retry=True,
)
celery_app.autodiscover_tasks(["app"])
