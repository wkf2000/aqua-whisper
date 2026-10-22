"""Download submission, status polling, and file serving API."""

from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

X_URL = "https://x.com/user/status/123"


def test_download_submission_enqueues_task() -> None:
    """An X.com URL is accepted and the task receives the fresh task id."""
    body = {"video_url": X_URL}
    with patch("app.main.run_video_download.apply_async") as mock_apply:
        response = client.post("/ui/download", json=body)
    assert response.status_code == 202
    mock_apply.assert_called_once_with(args=[response.json()["task_id"], body["video_url"]])


def test_download_submission_accepts_youtube_url() -> None:
    """YouTube URLs are accepted for downloads too."""
    body = {"video_url": "https://youtu.be/abc123def45"}
    with patch("app.main.run_video_download.apply_async") as mock_apply:
        response = client.post("/ui/download", json=body)
    assert response.status_code == 202
    mock_apply.assert_called_once_with(args=[response.json()["task_id"], body["video_url"]])


def test_download_submission_rejects_unsupported_url() -> None:
    """Non-YouTube, non-X URLs return the existing 400 error shape."""
    response = client.post("/ui/download", json={"video_url": "https://vimeo.com/123"})
    assert response.status_code == 400
    assert response.json() == {"detail": "video_url must be a YouTube or X.com URL"}


def test_download_status_pending_returns_pending_shape() -> None:
    """A missing result keeps the pending shape the frontend polls for."""
    with patch("app.main.get_task_result", return_value=None):
        response = client.get(f"/ui/download/{uuid4()}")
    assert response.status_code == 200
    assert response.json() == {"status": "pending"}


def test_download_status_returns_payload() -> None:
    """A stored result is returned unchanged."""
    payload = {"status": "success", "title": "T", "file_name": "T.mp4", "size_bytes": 5}
    with patch("app.main.get_task_result", return_value=payload):
        response = client.get(f"/ui/download/{uuid4()}")
    assert response.json() == payload


def test_download_file_serves_file_with_saved_name(tmp_path: Path) -> None:
    """The file is served under the file_name saved with the task result."""
    task_id = str(uuid4())
    file = tmp_path / f"{task_id}.mp4"
    file.write_bytes(b"video-bytes")
    with (
        patch("app.main.find_download_file", return_value=file),
        patch(
            "app.main.get_task_result",
            return_value={"status": "success", "file_name": "My Video.mp4"},
        ),
    ):
        response = client.get(f"/ui/download/file/{task_id}")
    assert response.status_code == 200
    assert response.content == b"video-bytes"
    # Starlette RFC 5987-encodes the attachment name (spaces become %20).
    assert "filename*=utf-8''My%20Video.mp4" in response.headers["content-disposition"]


def test_download_file_falls_back_when_result_expired(tmp_path: Path) -> None:
    """After the Redis result expires, the file is still served under a generic name."""
    task_id = str(uuid4())
    file = tmp_path / f"{task_id}.mp4"
    file.write_bytes(b"video-bytes")
    with (
        patch("app.main.find_download_file", return_value=file),
        patch("app.main.get_task_result", return_value=None),
    ):
        response = client.get(f"/ui/download/file/{task_id}")
    assert response.status_code == 200
    assert 'filename="video.mp4"' in response.headers["content-disposition"]


def test_download_file_rejects_non_uuid_task_id() -> None:
    """Ids that are not task-id-shaped never reach the filesystem."""
    response = client.get("/ui/download/file/not-a-uuid")
    assert response.status_code == 404
    assert response.json() == {"detail": "Download file not found"}


def test_download_file_missing_file_returns_404() -> None:
    """A well-formed id without a stored file returns 404."""
    with patch("app.main.find_download_file", return_value=None):
        response = client.get(f"/ui/download/file/{uuid4()}")
    assert response.status_code == 404


def test_index_page_serves_download_button() -> None:
    """The main page ships the download button and its result container."""
    response = client.get("/")
    assert response.status_code == 200
    assert 'id="download-btn"' in response.text
    assert 'id="download-result"' in response.text
