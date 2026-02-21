"""Tests for POST /transcript: body validation, YouTube URL, auth, and task enqueue."""

import os
from unittest.mock import patch

from fastapi.testclient import TestClient

# Set env before importing app so pydantic-settings picks them up.
os.environ.setdefault("API_KEY", "test-secret-key")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.main import app

client = TestClient(app)

VALID_BODY = {
    "video_url": "https://www.youtube.com/watch?v=abc123",
    "webhook_url": "https://example.com/webhook",
}


def test_transcript_valid_body_and_youtube_and_api_key_returns_202_with_task_id() -> None:
    """Valid body + valid YouTube URL + valid API key → 202 and JSON with task_id."""
    with patch("app.main.run_transcript_pipeline.apply_async") as mock_apply:
        mock_apply.return_value = None
        response = client.post(
            "/transcript",
            json=VALID_BODY,
            headers={"X-API-Key": "test-secret-key"},
        )
    assert response.status_code == 202
    data = response.json()
    assert "task_id" in data
    assert isinstance(data["task_id"], str)
    assert len(data["task_id"]) > 0
    mock_apply.assert_called_once()
    call_kwargs = mock_apply.call_args[1]
    args = call_kwargs["args"]
    assert args == [
        data["task_id"],
        VALID_BODY["video_url"],
        VALID_BODY["webhook_url"],
        "unknown",
    ]


def test_transcript_missing_video_url_returns_400() -> None:
    """Missing video_url in body → 400."""
    body = {"webhook_url": "https://example.com/webhook"}
    response = client.post(
        "/transcript",
        json=body,
        headers={"X-API-Key": "test-secret-key"},
    )
    assert response.status_code == 400


def test_transcript_missing_webhook_url_returns_400() -> None:
    """Missing webhook_url in body → 400."""
    body = {"video_url": "https://www.youtube.com/watch?v=abc123"}
    response = client.post(
        "/transcript",
        json=body,
        headers={"X-API-Key": "test-secret-key"},
    )
    assert response.status_code == 400


def test_transcript_non_youtube_url_returns_400() -> None:
    """Non-YouTube URL in video_url → 400."""
    body = {
        "video_url": "https://vimeo.com/123",
        "webhook_url": "https://example.com/webhook",
    }
    response = client.post(
        "/transcript",
        json=body,
        headers={"X-API-Key": "test-secret-key"},
    )
    assert response.status_code == 400


def test_transcript_author_defaults_to_unknown() -> None:
    """When author is omitted, it defaults to 'unknown' and is passed to the task."""
    with patch("app.main.run_transcript_pipeline.apply_async") as mock_apply:
        mock_apply.return_value = None
        response = client.post(
            "/transcript",
            json=VALID_BODY,
            headers={"X-API-Key": "test-secret-key"},
        )
    assert response.status_code == 202
    args = mock_apply.call_args[1]["args"]
    assert args[3] == "unknown"


def test_transcript_author_in_body_passed_to_task() -> None:
    """When author is provided in body, it is passed to the task."""
    with patch("app.main.run_transcript_pipeline.apply_async") as mock_apply:
        mock_apply.return_value = None
        response = client.post(
            "/transcript",
            json={**VALID_BODY, "author": "alice"},
            headers={"X-API-Key": "test-secret-key"},
        )
    assert response.status_code == 202
    args = mock_apply.call_args[1]["args"]
    assert args[3] == "alice"


def test_transcript_invalid_api_key_returns_401() -> None:
    """Invalid API key → 401."""
    response = client.post(
        "/transcript",
        json=VALID_BODY,
        headers={"X-API-Key": "wrong-key"},
    )
    assert response.status_code == 401
