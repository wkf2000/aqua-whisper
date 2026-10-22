"""Tests for the video download pipeline and its Celery task."""

import os
import time
from pathlib import Path
from unittest.mock import ANY, patch

import pytest

from app.config import settings
from app.download import (
    DownloadedVideo,
    download_video,
    find_download_file,
    purge_expired_downloads,
    safe_filename,
)
from app.pipeline import ProgressReporter
from app.tasks import run_video_download


@pytest.fixture
def download_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point DOWNLOAD_DIR at a temp dir and return it."""
    monkeypatch.setattr(settings, "DOWNLOAD_DIR", str(tmp_path))
    return tmp_path


def _write_output(cmd: list[str], _timeout: int) -> str:
    """Fake _run: write the file yt-dlp would produce for this command."""
    template = cmd[cmd.index("--output") + 1]
    out = Path(template.replace("%(ext)s", "mp4"))
    out.write_bytes(b"video-bytes")
    return ""


def test_download_video_reports_stages_and_result(download_dir: Path) -> None:
    """Both stage codes reach the progress callback; the result describes the file."""
    stages: list[str] = []
    with (
        patch(
            "app.download._probe_video",
            return_value={"title": "My Video", "live_status": "not_live"},
        ),
        patch("app.download._run", side_effect=_write_output),
    ):
        video = download_video("https://x.com/user/status/1", "task-1", progress=stages.append)
    assert stages == ["probing_video", "downloading_video"]
    assert video.path == download_dir / "task-1.mp4"
    assert video.title == "My Video"
    assert video.size_bytes == len(b"video-bytes")


def test_download_video_caps_height_and_avoids_playlists(download_dir: Path) -> None:
    """The yt-dlp command caps the height, skips playlists, and uses the download timeout."""
    commands: list[tuple[list[str], int]] = []

    def record_and_write(cmd: list[str], timeout: int) -> str:
        commands.append((cmd, timeout))
        return _write_output(cmd, timeout)

    with (
        patch("app.download._probe_video", return_value={"live_status": "not_live"}),
        patch("app.download._run", side_effect=record_and_write),
    ):
        download_video("https://www.youtube.com/watch?v=abc123def45", "task-2")

    cmd, timeout = commands[0]
    expected_format = (
        f"bv*[height<={settings.DOWNLOAD_MAX_HEIGHT}]+ba"
        f"/b[height<={settings.DOWNLOAD_MAX_HEIGHT}]"
        "/bv*+ba/b"
    )
    assert cmd[0] == "yt-dlp"
    assert "--no-playlist" in cmd
    assert expected_format in cmd
    assert timeout == settings.DOWNLOAD_TIMEOUT


def test_download_video_rejects_live_broadcast(download_dir: Path) -> None:
    """A reported live status is rejected before any download starts."""
    with patch("app.download._probe_video", return_value={"live_status": "is_live"}):
        with pytest.raises(RuntimeError, match="live status"):
            download_video("https://www.youtube.com/watch?v=abc123def45", "task-3")


def test_download_video_allows_missing_live_status(download_dir: Path) -> None:
    """X posts may not report live_status; they are treated as finished videos."""
    with (
        patch("app.download._probe_video", return_value={"title": "T"}),
        patch("app.download._run", side_effect=_write_output),
    ):
        video = download_video("https://x.com/user/status/1", "task-4")
    assert video.path.name == "task-4.mp4"


def test_download_video_fails_when_no_file_written(download_dir: Path) -> None:
    """A silent yt-dlp success that wrote nothing fails the task with a clear error."""
    with (
        patch("app.download._probe_video", return_value={"live_status": "not_live"}),
        patch("app.download._run", return_value=""),
    ):
        with pytest.raises(RuntimeError, match="without writing a video file"):
            download_video("https://x.com/user/status/1", "task-5")


def test_find_download_file_ignores_partials(download_dir: Path) -> None:
    """Partial yt-dlp files do not count as a finished download."""
    (download_dir / "task-6.mp4.part").write_bytes(b"x")
    (download_dir / "task-6.f6160.ytdl").write_bytes(b"x")
    assert find_download_file("task-6") is None
    (download_dir / "task-6.mp4").write_bytes(b"video")
    assert find_download_file("task-6") == download_dir / "task-6.mp4"


def test_find_download_file_missing_returns_none(download_dir: Path) -> None:
    """An unknown task id has no file."""
    assert find_download_file("missing") is None


def _age_file(path: Path, hours: float) -> None:
    """Set a file's timestamps to make it look `hours` old."""
    stamp = time.time() - hours * 3600
    os.utime(path, (stamp, stamp))


def test_purge_deletes_only_expired_files(download_dir: Path) -> None:
    """Files older than DOWNLOAD_TTL_HOURS are deleted; newer files stay."""
    expired = download_dir / "old.mp4"
    expired.write_bytes(b"x")
    _age_file(expired, settings.DOWNLOAD_TTL_HOURS + 1)
    fresh = download_dir / "fresh.mp4"
    fresh.write_bytes(b"y")
    purge_expired_downloads()
    assert not expired.exists()
    assert fresh.exists()


def test_purge_disabled_with_zero_ttl(download_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """DOWNLOAD_TTL_HOURS=0 keeps even long-expired files."""
    monkeypatch.setattr(settings, "DOWNLOAD_TTL_HOURS", 0)
    expired = download_dir / "old.mp4"
    expired.write_bytes(b"x")
    _age_file(expired, 1000)
    purge_expired_downloads()
    assert expired.exists()


def test_safe_filename_sanitizes_path_characters() -> None:
    """Path separators and reserved characters become underscores."""
    assert safe_filename('a/b\\c:d*e?f"g<h>i|j', ".mp4") == "a_b_c_d_e_f_g_h_i_j.mp4"


def test_safe_filename_truncates_long_titles() -> None:
    """Very long titles are cut so filenames stay filesystem-friendly."""
    assert len(safe_filename("x" * 300, ".mp4")) <= 104


def test_safe_filename_falls_back_to_video() -> None:
    """A missing or blank title yields the generic 'video' filename."""
    assert safe_filename(None, ".mp4") == "video.mp4"
    assert safe_filename("   ", ".mp4") == "video.mp4"


def test_download_task_saves_success_payload() -> None:
    """The task saves the file name, title, and size for frontend polling."""
    video = DownloadedVideo(
        path=Path("/data/downloads/task-1.mp4"), title="My Video", size_bytes=10
    )
    with (
        patch("app.tasks.purge_expired_downloads") as mock_purge,
        patch("app.tasks.download_video", return_value=video) as mock_download,
        patch("app.tasks.save_task_result") as mock_save,
    ):
        run_video_download.run("task-1", "https://x.com/user/status/1")
    mock_purge.assert_called_once_with()
    mock_download.assert_called_once_with("https://x.com/user/status/1", "task-1", progress=ANY)
    mock_save.assert_called_once_with(
        "task-1",
        {
            "status": "success",
            "title": "My Video",
            "file_name": "My Video.mp4",
            "size_bytes": 10,
        },
    )


def test_download_task_failure_keeps_error_shape() -> None:
    """A download failure saves the same failed result shape as transcript tasks."""
    with (
        patch("app.tasks.purge_expired_downloads"),
        patch("app.tasks.download_video", side_effect=RuntimeError("no video")),
        patch("app.tasks.save_task_result") as mock_save,
    ):
        run_video_download.run("task-1", "https://x.com/user/status/1")
    mock_save.assert_called_once_with("task-1", {"status": "failed", "error": "no video"})


def test_download_task_publishes_progress_stages() -> None:
    """Each pipeline stage is written to Redis; the payload carries the stage code."""

    def fake_download(
        _url: str, _task_id: str, progress: ProgressReporter | None = None
    ) -> DownloadedVideo:
        assert progress is not None
        progress("probing_video")
        progress("downloading_video")
        return DownloadedVideo(path=Path("/data/downloads/task-1.mp4"), title=None, size_bytes=1)

    stages: list[str] = []
    with (
        patch("app.tasks.purge_expired_downloads"),
        patch("app.tasks.download_video", side_effect=fake_download),
        patch(
            "app.tasks.save_task_progress", side_effect=lambda _task_id, stage: stages.append(stage)
        ),
        patch("app.tasks.save_task_result"),
    ):
        run_video_download.run("task-1", "https://x.com/user/status/1")
    assert stages == ["probing_video", "downloading_video"]
