"""Tests for Celery tasks: run_transcript_pipeline, webhook POST, and dedup."""

from unittest.mock import ANY, MagicMock, patch

import pytest

from app.db import StoredTranscript
from app.pipeline import NoSubtitlesError, VideoMetadata
from app.tasks import _transcript_with_dedup, run_transcript_pipeline, run_transcript_pipeline_ui

_META = VideoMetadata(
    title="Test Title", channel="Test Channel", duration=300.0, upload_date="2026-01-01"
)


def _stored(source: str, transcript: str, summary: str | None = None) -> StoredTranscript:
    """A stored row as the dedup path reads it back from the store."""
    return StoredTranscript(
        video_id="abc123def45",
        source=source,
        transcript=transcript,
        summary=summary,
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
        "summary": None,
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
    assert result == ("manual", "stored text", None)
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
    assert result == ("auto", "fresh text", None)
    mock_set.assert_called_once_with(
        "abc123def45",
        "auto",
        "fresh text",
        summary=None,
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
        patch("app.tasks.get_stored_transcript", return_value=None) as mock_get,
        patch("app.tasks.get_transcript", return_value=("whisper", "fresh text", _META)),
        patch("app.tasks.save_transcript") as mock_set,
    ):
        result = _transcript_with_dedup("https://www.youtube.com/watch?v=abc123def45")
    assert result == ("whisper", "fresh text", None)
    mock_get.assert_called_once_with("abc123def45")
    mock_set.assert_called_once_with(
        "abc123def45",
        "whisper",
        "fresh text",
        summary=None,
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
    assert result == ("auto", "text", None)


@pytest.mark.parametrize("summary", ["- Saved summary", "error"])
@pytest.mark.parametrize("summarize", [False, True])
def test_saved_summary_is_returned_without_llm(summary: str, summarize: bool) -> None:
    """Saved summaries are returned even when generation is disabled."""
    with (
        patch("app.tasks.get_stored_transcript", return_value=_stored("manual", "text", summary)),
        patch("app.tasks.get_transcript") as mock_get,
        patch("app.tasks.generate_summary") as mock_llm,
        patch("app.tasks.save_summary") as mock_save,
    ):
        result = _transcript_with_dedup("https://www.youtube.com/watch?v=abc123def45", summarize)
    assert result == ("manual", "text", summary)
    mock_get.assert_not_called()
    mock_llm.assert_not_called()
    mock_save.assert_not_called()


@pytest.mark.parametrize("summary", ["- New summary", "error"])
def test_missing_summary_is_generated_from_stored_transcript(summary: str) -> None:
    """Summarizing an old video only fills its summary, without re-transcribing."""
    with (
        patch("app.tasks.get_stored_transcript", return_value=_stored("auto", "old text")),
        patch("app.tasks.get_transcript") as mock_get,
        patch("app.tasks.generate_summary", return_value=summary) as mock_llm,
        patch("app.tasks.save_summary") as mock_save_summary,
        patch("app.tasks.save_transcript") as mock_save_transcript,
    ):
        result = _transcript_with_dedup(
            "https://www.youtube.com/watch?v=abc123def45", summarize=True
        )
    assert result == ("auto", "old text", summary)
    mock_llm.assert_called_once_with("old text")
    mock_save_summary.assert_called_once_with("abc123def45", summary)
    mock_get.assert_not_called()
    mock_save_transcript.assert_not_called()


def test_missing_summary_is_not_generated_when_disabled() -> None:
    """Transcript-only requests do not backfill an old video's missing summary."""
    with (
        patch("app.tasks.get_stored_transcript", return_value=_stored("auto", "old text")),
        patch("app.tasks.generate_summary") as mock_llm,
        patch("app.tasks.save_summary") as mock_save,
    ):
        assert _transcript_with_dedup("https://youtu.be/abc123def45") == ("auto", "old text", None)
    mock_llm.assert_not_called()
    mock_save.assert_not_called()


@pytest.mark.parametrize("summary", ["- Fresh summary", "error"])
def test_new_transcript_and_generated_summary_are_saved(summary: str) -> None:
    """New transcripts are saved with the generated summary, including failures."""
    with (
        patch("app.tasks.get_stored_transcript", return_value=None),
        patch("app.tasks.get_transcript", return_value=("manual", "fresh text", _META)),
        patch("app.tasks.generate_summary", return_value=summary) as mock_llm,
        patch("app.tasks.save_transcript") as mock_save,
    ):
        result = _transcript_with_dedup("https://youtu.be/abc123def45", summarize=True)
    assert result == ("manual", "fresh text", summary)
    mock_llm.assert_called_once_with("fresh text")
    mock_save.assert_called_once_with(
        "abc123def45",
        "manual",
        "fresh text",
        summary=summary,
        title=_META.title,
        channel=_META.channel,
        duration=_META.duration,
        upload_date=_META.upload_date,
    )


def test_new_transcript_skips_llm_when_disabled() -> None:
    """No LLM call is made for a new transcript-only request."""
    with (
        patch("app.tasks.get_stored_transcript", return_value=None),
        patch("app.tasks.get_transcript", return_value=("manual", "fresh text", _META)),
        patch("app.tasks.generate_summary") as mock_llm,
        patch("app.tasks.save_transcript"),
    ):
        assert _transcript_with_dedup("https://youtu.be/abc123def45") == (
            "manual",
            "fresh text",
            None,
        )
    mock_llm.assert_not_called()


def test_retranscribing_without_summary_returns_existing_summary() -> None:
    """Disabling dedup still preserves a summary for transcript-only requests."""
    with (
        patch("app.tasks.settings.TRANSCRIPT_DEDUP", False),
        patch(
            "app.tasks.get_stored_transcript",
            return_value=_stored("auto", "old text", "- Saved summary"),
        ),
        patch("app.tasks.get_transcript", return_value=("manual", "fresh text", _META)),
        patch("app.tasks.generate_summary") as mock_llm,
        patch("app.tasks.save_transcript") as mock_save,
    ):
        result = _transcript_with_dedup("https://youtu.be/abc123def45")
    assert result == ("manual", "fresh text", "- Saved summary")
    assert mock_save.call_args.kwargs["summary"] == "- Saved summary"
    mock_llm.assert_not_called()


def test_retranscribing_with_summary_refreshes_summary() -> None:
    """Explicit re-transcription generates a new summary when requested."""
    with (
        patch("app.tasks.settings.TRANSCRIPT_DEDUP", False),
        patch("app.tasks.get_stored_transcript") as mock_get,
        patch("app.tasks.get_transcript", return_value=("manual", "fresh text", _META)),
        patch("app.tasks.generate_summary", return_value="- Fresh summary") as mock_llm,
        patch("app.tasks.save_transcript"),
    ):
        result = _transcript_with_dedup("https://youtu.be/abc123def45", summarize=True)
    assert result == ("manual", "fresh text", "- Fresh summary")
    mock_get.assert_not_called()
    mock_llm.assert_called_once_with("fresh text")


def test_summary_store_failure_does_not_fail_cached_transcript() -> None:
    """A summary write failure does not lose an otherwise successful result."""
    with (
        patch("app.tasks.get_stored_transcript", return_value=_stored("auto", "old text")),
        patch("app.tasks.generate_summary", return_value="- Summary"),
        patch("app.tasks.save_summary", side_effect=RuntimeError("sqlite down")),
    ):
        assert _transcript_with_dedup("https://youtu.be/abc123def45", summarize=True) == (
            "auto",
            "old text",
            "- Summary",
        )


@pytest.mark.parametrize("summary", ["- Summary", "error", None])
def test_webhook_task_returns_transcript_and_summary(summary: str | None) -> None:
    """Summary failures retain a successful webhook payload with its transcript."""
    with (
        patch(
            "app.tasks._transcript_with_dedup", return_value=("manual", "text", summary)
        ) as mock_process,
        patch("app.tasks.httpx.Client") as mock_client_cls,
    ):
        run_transcript_pipeline.run("task-id", "video-url", "webhook-url", "author", True)
    mock_process.assert_called_once_with("video-url", True)
    payload = mock_client_cls.return_value.__enter__.return_value.post.call_args.kwargs["json"]
    assert payload == {
        "task_id": "task-id",
        "status": "success",
        "source": "manual",
        "transcript": "text",
        "summary": summary,
        "author": "author",
    }


@pytest.mark.parametrize("summary", ["- Summary", "error", None])
def test_ui_task_returns_transcript_and_summary(summary: str | None) -> None:
    """UI task results carry both fields, even when the summary is 'error'."""
    with (
        patch(
            "app.tasks._transcript_with_dedup", return_value=("auto", "text", summary)
        ) as mock_process,
        patch("app.tasks.save_task_result") as mock_save,
    ):
        run_transcript_pipeline_ui.run("task-id", "video-url", True)
    mock_process.assert_called_once_with("video-url", True, progress=ANY)
    mock_save.assert_called_once_with(
        "task-id",
        {"status": "success", "source": "auto", "transcript": "text", "summary": summary},
    )


def test_ui_task_transcription_failure_keeps_error_shape() -> None:
    """A transcription failure still returns the existing failed result shape."""
    with (
        patch("app.tasks._transcript_with_dedup", side_effect=RuntimeError("failed")),
        patch("app.tasks.save_task_result") as mock_save,
    ):
        run_transcript_pipeline_ui.run("task-id", "video-url", True)
    mock_save.assert_called_once_with("task-id", {"status": "failed", "error": "failed"})


def test_ui_task_publishes_progress_stages() -> None:
    """The UI task writes each stage to Redis so the frontend can show progress."""
    with (
        patch("app.tasks.get_stored_transcript", return_value=None),
        patch("app.tasks.get_transcript", return_value=("manual", "text", _META)) as mock_pipeline,
        patch("app.tasks.generate_summary", return_value="- Summary"),
        patch("app.tasks.save_transcript"),
        patch("app.tasks.save_task_progress") as mock_progress,
        patch("app.tasks.save_task_result") as mock_save,
    ):
        run_transcript_pipeline_ui.run("task-id", "https://youtu.be/abc123def45", True)
        assert [call.args for call in mock_progress.call_args_list] == [
            ("task-id", "checking_saved"),
            ("task-id", "summarizing"),
        ]
        # The pipeline receives a callback that writes stage updates to Redis.
        progress = mock_pipeline.call_args.args[1]
        progress("downloading_subtitles")
        mock_progress.assert_any_call("task-id", "downloading_subtitles")
    mock_save.assert_called_once()


def test_ui_task_progress_store_failure_does_not_fail_job() -> None:
    """A Redis failure while writing a stage update must not fail the task."""
    with (
        patch("app.tasks.get_stored_transcript", return_value=None),
        patch("app.tasks.get_transcript", return_value=("manual", "text", _META)),
        patch("app.tasks.generate_summary", return_value="- Summary"),
        patch("app.tasks.save_transcript"),
        patch("app.tasks.save_task_progress", side_effect=RuntimeError("redis down")),
        patch("app.tasks.save_task_result") as mock_save,
    ):
        run_transcript_pipeline_ui.run("task-id", "https://youtu.be/abc123def45", True)
    mock_save.assert_called_once_with(
        "task-id",
        {"status": "success", "source": "manual", "transcript": "text", "summary": "- Summary"},
    )


def test_dedup_hit_generating_summary_reports_summarizing() -> None:
    """Generating a missing summary from a stored row reports the summarizing stage."""
    stages: list[str] = []
    with (
        patch("app.tasks.get_stored_transcript", return_value=_stored("auto", "old text")),
        patch("app.tasks.generate_summary", return_value="- Summary"),
        patch("app.tasks.save_summary"),
    ):
        _transcript_with_dedup(
            "https://youtu.be/abc123def45", summarize=True, progress=stages.append
        )
    assert stages == ["checking_saved", "summarizing"]
