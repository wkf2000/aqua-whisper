"""Video file downloads with yt-dlp: probe, download to disk, expire old files.

Videos from YouTube and X are downloaded to DOWNLOAD_DIR under the
server-generated task id, so no part of the user-supplied URL ends up in a
file path. Live broadcasts are rejected up front with a clear error: fetching
one would run until the timeout instead of producing a complete file. X posts
without a reported live status are treated as finished videos.
"""

import re
import time
from pathlib import Path
from typing import Any, NamedTuple

import structlog

from app.config import settings
from app.pipeline import ALLOWED_LIVE_STATUSES, ProgressReporter, _probe_video, _run

logger = structlog.get_logger()

# yt-dlp intermediate files that are still being written, not finished downloads.
_PARTIAL_SUFFIXES = {".part", ".ytdl"}

# Characters a Content-Disposition filename must not carry.
_UNSAFE_FILENAME_CHARS = re.compile(r"[\\/:*?\"<>|\x00-\x1f]+")


class DownloadedVideo(NamedTuple):
    """A finished download: its local path, title, and size in bytes."""

    path: Path
    title: str | None
    size_bytes: int


def download_dir() -> Path:
    """The configured download directory, created on demand."""
    path = Path(settings.DOWNLOAD_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def find_download_file(task_id: str) -> Path | None:
    """Return the finished file downloaded under task_id, or None if there is none.

    Partial yt-dlp files (.part, .ytdl) are still being written and do not count.
    """
    for path in sorted(download_dir().glob(f"{task_id}.*")):
        if path.is_file() and path.suffix.lower() not in _PARTIAL_SUFFIXES:
            return path
    return None


def purge_expired_downloads() -> None:
    """Delete download files older than DOWNLOAD_TTL_HOURS; 0 disables purging.

    Runs at the start of each download task instead of on a timer.
    """
    ttl_hours = settings.DOWNLOAD_TTL_HOURS
    if ttl_hours <= 0:
        return
    cutoff = time.time() - ttl_hours * 3600
    for path in download_dir().iterdir():
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
                logger.info("download.purged_file", file=str(path))
        except OSError:
            logger.warning("download.purge_failed", file=str(path))


def safe_filename(title: str | None, suffix: str) -> str:
    """A header-safe download filename built from the video's title."""
    stem = _UNSAFE_FILENAME_CHARS.sub("_", (title or "").strip())[:100].strip(" ._")
    return f"{stem or 'video'}{suffix}"


def _check_live_status(info: dict[str, Any]) -> None:
    """Reject live broadcasts; a missing live status (e.g. X posts) is accepted."""
    live_status = info.get("live_status")
    if live_status is not None and live_status not in ALLOWED_LIVE_STATUSES:
        raise RuntimeError(
            f"Video live status {live_status!r} is not supported; "
            "only finished videos can be downloaded"
        )


def download_video(
    video_url: str, task_id: str, progress: ProgressReporter | None = None
) -> DownloadedVideo:
    """Download one video from video_url into DOWNLOAD_DIR under task_id.

    The optional progress callback receives "probing_video" and
    "downloading_video" stage codes. Videos are capped at
    DOWNLOAD_MAX_HEIGHT; when no format at or below that height exists,
    yt-dlp falls back to the best available one.
    """
    if progress is not None:
        progress("probing_video")
    info = _probe_video(video_url)
    _check_live_status(info)
    title_raw: Any = info.get("title")
    title = title_raw if isinstance(title_raw, str) and title_raw.strip() else None

    logger.info("download_video.start", task_id=task_id, video_url=video_url)
    if progress is not None:
        progress("downloading_video")
    _run(
        [
            "yt-dlp",
            "--no-playlist",
            "-f",
            f"bv*[height<={settings.DOWNLOAD_MAX_HEIGHT}]+ba"
            f"/b[height<={settings.DOWNLOAD_MAX_HEIGHT}]"
            "/bv*+ba/b",
            "--merge-output-format",
            "mp4",
            "--output",
            f"{download_dir() / task_id}.%(ext)s",
            video_url,
        ],
        settings.DOWNLOAD_TIMEOUT,
    )
    path = find_download_file(task_id)
    if path is None:
        raise RuntimeError("yt-dlp finished without writing a video file")
    size_bytes = path.stat().st_size
    logger.info(
        "download_video.success",
        task_id=task_id,
        video_url=video_url,
        file=str(path),
        size_bytes=size_bytes,
    )
    return DownloadedVideo(path=path, title=title, size_bytes=size_bytes)
