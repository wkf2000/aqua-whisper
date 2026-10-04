"""Celery tasks: run transcript pipeline and POST result to webhook."""

import httpx
import structlog
from opentelemetry import trace

from app.celery_app import celery_app
from app.config import settings
from app.db import get_stored_transcript, save_summary, save_transcript
from app.pipeline import ProgressReporter, get_transcript
from app.store import save_task_progress, save_task_result
from app.summary import generate_summary
from app.youtube import extract_video_id

logger = structlog.get_logger()
tracer = trace.get_tracer(__name__)


def _transcript_with_dedup(
    video_url: str, summarize: bool = False, progress: ProgressReporter | None = None
) -> tuple[str, str, str | None]:
    """Return source, transcript, and optional summary, reusing stored results.

    The optional progress callback receives one stage code per step
    ("checking_saved", "downloading_subtitles", "summarizing", ...).
    """
    video_id = extract_video_id(video_url)
    stored = None
    # Even when re-transcribing, a transcript-only request returns any saved summary.
    if video_id and (settings.TRANSCRIPT_DEDUP or not summarize):
        if progress is not None:
            progress("checking_saved")
        try:
            stored = get_stored_transcript(video_id)
        except Exception:
            # A store failure must not fail the job; fall through to the pipeline.
            logger.warning("transcript_store.read_failed", video_url=video_url, video_id=video_id)
            stored = None
        if stored is not None and settings.TRANSCRIPT_DEDUP:
            logger.info(
                "transcript_store.hit",
                video_url=video_url,
                video_id=video_id,
                source=stored.source,
            )
            summary = stored.summary
            if summarize and summary is None:
                if progress is not None:
                    progress("summarizing")
                summary = generate_summary(stored.transcript)
                try:
                    save_summary(video_id, summary)
                except Exception:
                    logger.warning("transcript_store.write_failed", video_id=video_id)
            return stored.source, stored.transcript, summary
        if stored is None:
            logger.info("transcript_store.miss", video_url=video_url, video_id=video_id)
    source, transcript, metadata = get_transcript(video_url, progress)
    summary = stored.summary if stored else None
    if summarize:
        if progress is not None:
            progress("summarizing")
        summary = generate_summary(transcript)
    if video_id:
        try:
            save_transcript(
                video_id,
                source,
                transcript,
                summary=summary,
                title=metadata.title,
                channel=metadata.channel,
                duration=metadata.duration,
                upload_date=metadata.upload_date,
            )
        except Exception:
            logger.warning("transcript_store.write_failed", video_url=video_url, video_id=video_id)
    return source, transcript, summary


@celery_app.task
def run_transcript_pipeline(
    task_id: str,
    video_url: str,
    webhook_url: str,
    author: str = "unknown",
    summarize: bool = False,
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
            source, transcript, summary = _transcript_with_dedup(video_url, summarize)
            payload = {
                "task_id": task_id,
                "status": "success",
                "source": source,
                "transcript": transcript,
                "summary": summary,
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
def run_transcript_pipeline_ui(task_id: str, video_url: str, summarize: bool = False) -> None:
    """Run transcript pipeline and store result in Redis for frontend polling."""
    with tracer.start_as_current_span("run_transcript_pipeline_ui") as span:
        span.set_attribute("task.id", task_id)
        span.set_attribute("video.url", video_url)

        def save_progress(stage: str) -> None:
            """Write one stage update to Redis; a store failure must not fail the job."""
            try:
                save_task_progress(task_id, stage)
            except Exception:
                logger.warning("task_progress.write_failed", task_id=task_id, stage=stage)

        logger.info(
            "run_transcript_pipeline_ui.start",
            task_id=task_id,
            video_url=video_url,
        )
        try:
            source, transcript, summary = _transcript_with_dedup(
                video_url, summarize, progress=save_progress
            )
            payload = {
                "status": "success",
                "source": source,
                "transcript": transcript,
                "summary": summary,
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
