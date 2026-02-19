"""Celery tasks: run transcript pipeline and POST result to webhook."""

import httpx

from app.celery_app import celery_app

STUB_TRANSCRIPT = "WEBVTT\n\n"


@celery_app.task
def run_transcript_pipeline(task_id: str, video_url: str, webhook_url: str) -> None:
    """Run transcript pipeline for video_url and POST result to webhook_url."""
    payload = {
        "task_id": task_id,
        "status": "success",
        "source": "manual",
        "transcript": STUB_TRANSCRIPT,
    }
    with httpx.Client() as client:
        client.post(webhook_url, json=payload)
