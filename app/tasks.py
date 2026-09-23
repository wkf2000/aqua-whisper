"""Celery tasks: run transcript pipeline and POST result to webhook."""

import httpx
import structlog
from opentelemetry import trace

from app.celery_app import celery_app
from app.config import settings
from app.db import get_stored_transcript, save_transcript
from app.pipeline import get_transcript
from app.store import save_task_result
from app.youtube import extract_video_id

logger = structlog.get_logger()
tracer = trace.get_tracer(__name__)


def _transcript_with_dedup(video_url: str) -> tuple[str, str]:
    """Return (source, transcript), skipping videos already in the store when enabled."""
    video_id = extract_video_id(video_url)
    if video_id and settings.TRANSCRIPT_DEDUP:
        try:
            stored = get_stored_transcript(video_id)
        except Exception:
            # A store failure must not fail the job; fall through to the pipeline.
            logger.warning("transcript_store.read_failed", video_url=video_url, video_id=video_id)
            stored = None
        if stored is not None:
            logger.info(
                "transcript_store.hit",
                video_url=video_url,
                video_id=video_id,
                source=stored.source,
            )
            return stored.source, stored.transcript
        logger.info("transcript_store.miss", video_url=video_url, video_id=video_id)
    source, transcript, metadata = get_transcript(video_url)
    if video_id:
        try:
            save_transcript(
                video_id,
                source,
                transcript,
                title=metadata.title,
                channel=metadata.channel,
                duration=metadata.duration,
                upload_date=metadata.upload_date,
            )
        except Exception:
            logger.warning("transcript_store.write_failed", video_url=video_url, video_id=video_id)
    return source, transcript


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
            source, transcript = _transcript_with_dedup(video_url)
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
            source, transcript = _transcript_with_dedup(video_url)
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
