"""Redis-backed task-result storage."""

import json
from unittest.mock import patch

from app.store import get_task_result, save_task_progress


def test_save_task_progress_writes_pending_stage_row() -> None:
    """A stage update keeps status "pending" and is overwritten by the final result."""
    with patch("app.store._redis") as mock_redis:
        save_task_progress("task-id", "transcribing_audio")
    mock_redis.set.assert_called_once_with(
        "ui:task:task-id",
        json.dumps({"status": "pending", "stage": "transcribing_audio"}),
        ex=3600,
    )


def test_get_task_result_parses_stored_row() -> None:
    """A stored row round-trips through JSON, including stage updates."""
    with patch("app.store._redis") as mock_redis:
        mock_redis.get.return_value = '{"status": "pending", "stage": "summarizing"}'
        assert get_task_result("task-id") == {"status": "pending", "stage": "summarizing"}
        mock_redis.get.return_value = None
        assert get_task_result("missing") is None
