"""UI submission flags and polling results."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


@pytest.mark.parametrize("summarize", [None, False, True])
def test_ui_submission_passes_summarize_flag(summarize: bool | None) -> None:
    body: dict[str, str | bool] = {"video_url": "https://youtu.be/abc123def45"}
    if summarize is not None:
        body["summarize"] = summarize
    with patch("app.main.run_transcript_pipeline_ui.apply_async") as mock_apply:
        response = client.post("/ui/transcript", json=body)
    assert response.status_code == 202
    mock_apply.assert_called_once_with(
        args=[response.json()["task_id"], body["video_url"], summarize is True]
    )


@pytest.mark.parametrize("summary", [None, "- A summary", "error"])
def test_ui_polling_returns_transcript_and_summary(summary: str | None) -> None:
    payload = {"status": "success", "source": "manual", "transcript": "text", "summary": summary}
    with patch("app.main.get_task_result", return_value=payload):
        response = client.get("/ui/transcript/task-id")
    assert response.status_code == 200
    assert response.json() == payload


def test_ui_pending_result_keeps_existing_shape() -> None:
    with patch("app.main.get_task_result", return_value=None):
        response = client.get("/ui/transcript/task-id")
    assert response.json() == {"status": "pending"}


def test_ui_pending_result_can_carry_stage() -> None:
    """A stage row keeps status pending and adds the stage code for the frontend."""
    with patch(
        "app.main.get_task_result", return_value={"status": "pending", "stage": "summarizing"}
    ):
        response = client.get("/ui/transcript/task-id")
    assert response.json() == {"status": "pending", "stage": "summarizing"}
