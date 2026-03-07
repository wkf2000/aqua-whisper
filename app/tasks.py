"""Celery tasks: run transcript pipeline and POST result to webhook."""

import httpx
import structlog
from opentelemetry import trace

from app.celery_app import celery_app
from app.pipeline import get_transcript
from app.store import save_task_result

logger = structlog.get_logger()
tracer = trace.get_tracer(__name__)


@celery_app.task
def run_transcript_pipeline(
    task_id: str, video_url: str, webhook_url: str, author: str = "unknown"
) -> None:
    """Run transcript pipeline for video_url and POST result to webhook_url."""
    with tracer.start_as_current_span("run_transcript_pipeline") as span:
        span.set_attribute("task.id", task_id)
        span.set_attribute("video.url", video_url)
        span.set_attribute("webhook.url", webhook_url)
        span.set_attribute("author", author)

        logger.info(
            "run_transcript_pipeline.start",
            task_id=task_id,
            video_url=video_url,
            webhook_url=webhook_url,
            author=author,
        )
        try:
            source, transcript = get_transcript(video_url)
            payload = {
                "task_id": task_id,
                "status": "success",
                "source": source,
                "transcript": transcript,
                "author": author,
            }
            logger.info(
                "run_transcript_pipeline.success",
                task_id=task_id,
                video_url=video_url,
                source=source,
                author=author,
            )
        except Exception as e:  # noqa: BLE001
            logger.error(
                "run_transcript_pipeline.failed",
                task_id=task_id,
                video_url=video_url,
                author=author,
                error=str(e),
            )
            payload = {
                "task_id": task_id,
                "status": "failed",
                "error": str(e),
                "author": author,
            }
        with httpx.Client() as client:
            client.post(webhook_url, json=payload)


@celery_app.task
def run_transcript_pipeline_ui(task_id: str, video_url: str) -> None:
    """Run transcript pipeline and store result in Redis for frontend polling."""
    with tracer.start_as_current_span("run_transcript_pipeline_ui") as span:
        span.set_attribute("task.id", task_id)
        span.set_attribute("video.url", video_url)

        logger.info(
            "run_transcript_pipeline_ui.start",
            task_id=task_id,
            video_url=video_url,
        )
        try:
            source, transcript = get_transcript(video_url)
            payload = {
                "status": "success",
                "source": source,
                "transcript": transcript,
            }
            logger.info(
                "run_transcript_pipeline_ui.success",
                task_id=task_id,
                video_url=video_url,
                source=source,
            )
        except Exception as e:  # noqa: BLE001
            logger.error(
                "run_transcript_pipeline_ui.failed",
                task_id=task_id,
                video_url=video_url,
                error=str(e),
            )
            payload = {
                "status": "failed",
                "error": str(e),
            }
        save_task_result(task_id, payload)
