"""Celery tasks: run transcript pipeline and POST result to webhook."""

import httpx

from app.celery_app import celery_app
from app.pipeline import get_transcript


@celery_app.task
def run_transcript_pipeline(
    task_id: str, video_url: str, webhook_url: str, author: str = "unknown"
) -> None:
    """Run transcript pipeline for video_url and POST result to webhook_url."""
    try:
        source, transcript = get_transcript(video_url)
        payload = {
            "task_id": task_id,
            "status": "success",
            "source": source,
            "transcript": transcript,
            "author": author,
        }
    except Exception as e:
        payload = {
            "task_id": task_id,
            "status": "failed",
            "error": str(e),
            "author": author,
        }
    with httpx.Client() as client:
        client.post(webhook_url, json=payload)
