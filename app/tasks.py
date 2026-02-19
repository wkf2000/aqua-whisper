"""Celery tasks. run_transcript_pipeline will be implemented in Task 5."""

from app.celery_app import celery_app


@celery_app.task
def run_transcript_pipeline(task_id: str, video_url: str, webhook_url: str) -> None:
    """Stub: run transcript pipeline for video_url and POST result to webhook_url. Task 5 implements."""
    pass
