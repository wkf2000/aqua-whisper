"""Tests for Celery task: run_transcript_pipeline and webhook POST."""

from unittest.mock import MagicMock, patch

import pytest

from app.pipeline import NoSubtitlesError
from app.tasks import run_transcript_pipeline


def test_task_posts_success_payload_when_get_transcript_returns() -> None:
    """When get_transcript returns (source, transcript), task POSTs webhook with status success."""
    task_id = "task-uuid-123"
    video_url = "https://www.youtube.com/watch?v=abc"
    webhook_url = "https://example.com/webhook"
    source = "manual"
    transcript = "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nline one"

    mock_post = MagicMock()
    mock_client = MagicMock()
    mock_client.post = mock_post

    with (
        patch("app.tasks.get_transcript", return_value=(source, transcript)),
        patch("app.tasks.httpx.Client") as mock_client_cls,
    ):
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_client_cls.return_value.__exit__.return_value = None
        run_transcript_pipeline.run(task_id, video_url, webhook_url)

    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    assert call_kwargs[0][0] == webhook_url
    assert call_kwargs[1]["json"] == {
        "task_id": task_id,
        "status": "success",
        "source": source,
        "transcript": transcript,
    }


def test_task_posts_failed_payload_when_get_transcript_raises() -> None:
    """When get_transcript raises, task POSTs webhook with status failed and error message."""
    task_id = "task-uuid-456"
    video_url = "https://www.youtube.com/watch?v=xyz"
    webhook_url = "https://example.com/callback"
    error_message = "No manual or auto subtitles available for this video"

    mock_post = MagicMock()
    mock_client = MagicMock()
    mock_client.post = mock_post

    with (
        patch("app.tasks.get_transcript", side_effect=NoSubtitlesError(error_message)),
        patch("app.tasks.httpx.Client") as mock_client_cls,
    ):
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_client_cls.return_value.__exit__.return_value = None
        run_transcript_pipeline.run(task_id, video_url, webhook_url)

    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    assert call_kwargs[0][0] == webhook_url
    assert call_kwargs[1]["json"] == {
        "task_id": task_id,
        "status": "failed",
        "error": error_message,
    }


def test_task_posts_failed_payload_on_any_exception() -> None:
    """When get_transcript raises any Exception, task POSTs webhook with status failed."""
    task_id = "task-uuid-789"
    video_url = "https://www.youtube.com/watch?v=err"
    webhook_url = "https://example.com/hook"
    error_message = "Unexpected runtime error"

    mock_post = MagicMock()
    mock_client = MagicMock()
    mock_client.post = mock_post

    with (
        patch("app.tasks.get_transcript", side_effect=RuntimeError(error_message)),
        patch("app.tasks.httpx.Client") as mock_client_cls,
    ):
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_client_cls.return_value.__exit__.return_value = None
        run_transcript_pipeline.run(task_id, video_url, webhook_url)

    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    assert call_kwargs[1]["json"]["status"] == "failed"
    assert call_kwargs[1]["json"]["error"] == error_message
