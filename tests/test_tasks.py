"""Tests for Celery tasks: run_transcript_pipeline, webhook POST, and dedup."""

from unittest.mock import MagicMock, patch

from app.db import StoredTranscript
from app.pipeline import NoSubtitlesError, VideoMetadata
from app.tasks import _transcript_with_dedup, run_transcript_pipeline

_META = VideoMetadata(
    title="Test Title", channel="Test Channel", duration=300.0, upload_date="2026-01-01"
)


def _stored(source: str, transcript: str) -> StoredTranscript:
    """A stored row as the dedup path reads it back from the store."""
    return StoredTranscript(
        video_id="abc123def45",
        source=source,
        transcript=transcript,
        title=None,
        channel=None,
        duration=None,
        upload_date=None,
        created_at="2026-09-23 00:00:00",
        updated_at="2026-09-23 00:00:00",
    )


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
        patch("app.tasks.get_transcript", return_value=(source, transcript, _META)),
        patch("app.tasks.httpx.Client") as mock_client_cls,
    ):
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_client_cls.return_value.__exit__.return_value = None
        run_transcript_pipeline.run(task_id, video_url, webhook_url, "unknown")

    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    assert call_kwargs[0][0] == webhook_url
    assert call_kwargs[1]["json"] == {
        "task_id": task_id,
        "status": "success",
        "source": source,
        "transcript": transcript,
        "author": "unknown",
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
        run_transcript_pipeline.run(task_id, video_url, webhook_url, "unknown")

    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    assert call_kwargs[0][0] == webhook_url
    assert call_kwargs[1]["json"] == {
        "task_id": task_id,
        "status": "failed",
        "error": error_message,
        "author": "unknown",
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
        run_transcript_pipeline.run(task_id, video_url, webhook_url, "unknown")

    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    assert call_kwargs[1]["json"]["status"] == "failed"
    assert call_kwargs[1]["json"]["error"] == error_message
    assert call_kwargs[1]["json"]["author"] == "unknown"


def test_stored_transcript_skips_pipeline() -> None:
    """When the video is already in the store, the pipeline is not run."""
    with (
        patch("app.tasks.extract_video_id", return_value="abc123def45"),
        patch("app.tasks.get_stored_transcript", return_value=_stored("manual", "stored text")),
        patch("app.tasks.get_transcript") as mock_get,
        patch("app.tasks.save_transcript") as mock_set,
    ):
        result = _transcript_with_dedup("https://www.youtube.com/watch?v=abc123def45")
    assert result == ("manual", "stored text")
    mock_get.assert_not_called()
    mock_set.assert_not_called()


def test_unstored_transcript_runs_pipeline_and_saves() -> None:
    """When the video is not in the store, the pipeline runs and its result is saved."""
    with (
        patch("app.tasks.extract_video_id", return_value="abc123def45"),
        patch("app.tasks.get_stored_transcript", return_value=None),
        patch("app.tasks.get_transcript", return_value=("auto", "fresh text", _META)),
        patch("app.tasks.save_transcript") as mock_set,
    ):
        result = _transcript_with_dedup("https://www.youtube.com/watch?v=abc123def45")
    assert result == ("auto", "fresh text")
    mock_set.assert_called_once_with(
        "abc123def45",
        "auto",
        "fresh text",
        title=_META.title,
        channel=_META.channel,
        duration=_META.duration,
        upload_date=_META.upload_date,
    )


def test_dedup_disabled_when_flag_false() -> None:
    """TRANSCRIPT_DEDUP=false skips the store check; the pipeline runs and saves."""
    with (
        patch("app.tasks.extract_video_id", return_value="abc123def45"),
        patch("app.tasks.settings.TRANSCRIPT_DEDUP", False),
        patch("app.tasks.get_stored_transcript") as mock_get,
        patch("app.tasks.get_transcript", return_value=("whisper", "fresh text", _META)),
        patch("app.tasks.save_transcript") as mock_set,
    ):
        result = _transcript_with_dedup("https://www.youtube.com/watch?v=abc123def45")
    assert result == ("whisper", "fresh text")
    mock_get.assert_not_called()
    mock_set.assert_called_once_with(
        "abc123def45",
        "whisper",
        "fresh text",
        title=_META.title,
        channel=_META.channel,
        duration=_META.duration,
        upload_date=_META.upload_date,
    )


def test_store_read_failure_still_runs_pipeline() -> None:
    """A store error on read falls through to running the pipeline."""
    with (
        patch("app.tasks.extract_video_id", return_value="abc123def45"),
        patch("app.tasks.get_stored_transcript", side_effect=RuntimeError("sqlite down")),
        patch("app.tasks.get_transcript", return_value=("auto", "text", _META)),
        patch("app.tasks.save_transcript"),
    ):
        result = _transcript_with_dedup("https://www.youtube.com/watch?v=abc123def45")
    assert result == ("auto", "text")
