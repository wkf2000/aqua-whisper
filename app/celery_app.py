"""Celery app configuration."""

from celery import Celery

from app.config import settings

celery_app = Celery(
    "aqua_whisper",
    broker=settings.REDIS_URL,
    # No result_backend: webhook-only design, no GET /tasks.
)
celery_app.autodiscover_tasks(["app"])
