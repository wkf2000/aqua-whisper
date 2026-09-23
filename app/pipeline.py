"""Transcript pipeline: yt-dlp manual/auto subtitles, then Whisper fallback.

Always returns plain text. Videos not longer than 60 seconds are rejected up
front with a clear error instead of the old misleading "no subtitles" one.
"""

import shutil
import subprocess
from pathlib import Path
from tempfile import mkdtemp

import structlog
from faster_whisper import BatchedInferencePipeline

from app.config import settings
from app.whisper import get_model

logger = structlog.get_logger()

MIN_VIDEO_DURATION = 60

# yt-dlp calls fail fast after these timeouts instead of hanging a worker forever.
_SUBTITLE_TIMEOUT = 120
_AUDIO_TIMEOUT = 900

# Suffixes accepted after the audio-only download for faster-whisper (PyAV decode).
_AUDIO_EXTS = {
    ".mp3",
    ".m4a",
    ".webm",
    ".weba",
    ".opus",
    ".aac",
    ".ogg",
    ".oga",
    ".wav",
    ".flac",
    ".mp4",
    ".mkv",
}


class NoSubtitlesError(Exception):
    """Raised when no manual or auto subtitles are available for the video."""


class VideoTooShortError(Exception):
    """Raised when the video is not longer than MIN_VIDEO_DURATION seconds."""


def _run(cmd: list[str], timeout: int) -> None:
    """Run a yt-dlp command; raise a clear error on non-zero exit or timeout."""
    logger.info("yt_dlp.run", command=cmd[0], args=cmd[1:])
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"yt-dlp timed out after {timeout}s") from exc
    if result.returncode != 0:
        stderr = (result.stderr or b"").decode("utf-8", "replace").strip()[-500:]
        raise RuntimeError(
            f"yt-dlp failed with exit code {result.returncode}: {stderr or 'no stderr output'}"
        )


def _vtt_to_plain_text(vtt: str) -> str:
    """Strip VTT markup and collapse consecutive duplicate caption lines."""
    lines: list[str] = []
    prev: str | None = None
    for raw in vtt.splitlines():
        line = raw.strip()
        if not line or line.startswith("WEBVTT") or "-->" in line:
            continue
        if line == prev:
            continue
        lines.append(line)
        prev = line
    return "\n".join(lines)


def _plain_lines(segments) -> list[str]:
    """Collapse transcribed segments into deduplicated plain text lines."""
    lines: list[str] = []
    prev: str | None = None
    for seg in segments:
        text = getattr(seg, "text", "").strip()
        if not text or text == prev:
            continue
        lines.append(text)
        prev = text
    return lines


def _check_duration(video_url: str) -> None:
    """Fetch duration up front; reject videos not longer than MIN_VIDEO_DURATION."""
    result = subprocess.run(
        ["yt-dlp", "--skip-download", "--print", "%(duration)s", video_url],
        capture_output=True,
        timeout=_SUBTITLE_TIMEOUT,
    )
    if result.returncode != 0:
        stderr = (result.stderr or b"").decode("utf-8", "replace").strip()[-500:]
        raise RuntimeError(f"yt-dlp failed to fetch video info: {stderr or 'no stderr output'}")
    stdout = result.stdout.decode("utf-8", "replace").strip()
    try:
        duration = float(stdout)
    except ValueError as exc:
        raise RuntimeError(f"yt-dlp returned an unparseable duration: {stdout!r}") from exc
    if duration <= MIN_VIDEO_DURATION:
        raise VideoTooShortError(
            f"Video is {duration:.0f}s long; only videos longer than "
            f"{MIN_VIDEO_DURATION}s are supported"
        )


def get_transcript(video_url: str) -> tuple[str, str]:
    """Return (source, plain_text). Raises NoSubtitlesError if no transcript available."""
    logger.info("get_transcript.start", video_url=video_url)
    _check_duration(video_url)
    temp_dir = mkdtemp()
    try:
        out_base = str(Path(temp_dir) / "subs")

        # Try manual subtitles first.
        logger.info("get_transcript.try_manual_subtitles", video_url=video_url)
        _run(
            [
                "yt-dlp",
                "--match-filter",
                f"duration>{MIN_VIDEO_DURATION}",
                "--write-sub",
                "--sub-langs",
                settings.SUBTITLE_LANGS,
                "--skip-download",
                "--output",
                out_base,
                video_url,
            ],
            _SUBTITLE_TIMEOUT,
        )
        vtt_files = list(Path(temp_dir).glob("*.vtt"))
        if vtt_files:
            logger.info("get_transcript.manual_subtitles_found", video_url=video_url)
            return ("manual", _vtt_to_plain_text(vtt_files[0].read_text()))

        # Try auto-generated subtitles.
        logger.info("get_transcript.try_auto_subtitles", video_url=video_url)
        _run(
            [
                "yt-dlp",
                "--match-filter",
                f"duration>{MIN_VIDEO_DURATION}",
                "--write-auto-sub",
                "--sub-langs",
                settings.SUBTITLE_LANGS,
                "--skip-download",
                "--output",
                out_base,
                video_url,
            ],
            _SUBTITLE_TIMEOUT,
        )
        vtt_files = list(Path(temp_dir).glob("*.vtt"))
        if vtt_files:
            logger.info("get_transcript.auto_subtitles_found", video_url=video_url)
            return ("auto", _vtt_to_plain_text(vtt_files[0].read_text()))

        # Whisper fallback: download audio-only with yt-dlp, transcribe with faster-whisper.
        logger.info("get_transcript.whisper_fallback_start", video_url=video_url)
        audio_out = str(Path(temp_dir) / "audio_%(id)s.%(ext)s")
        _run(
            [
                "yt-dlp",
                "--match-filter",
                f"duration>{MIN_VIDEO_DURATION}",
                "-f",
                "ba/b",
                "--output",
                audio_out,
                video_url,
            ],
            _AUDIO_TIMEOUT,
        )
        audio_files = [
            p
            for p in Path(temp_dir).iterdir()
            if p.suffix.lower() in _AUDIO_EXTS and not p.name.endswith((".part", ".ytdl"))
        ]
        if not audio_files:
            logger.error("get_transcript.no_audio_downloaded_for_whisper", video_url=video_url)
            raise NoSubtitlesError("No manual or auto subtitles available for this video")
        audio_path = str(audio_files[0])
        model = get_model()
        if settings.WHISPER_BATCHED:
            segments, _ = BatchedInferencePipeline(model).transcribe(
                audio_path, vad_filter=True, batch_size=8
            )
        else:
            segments, _ = model.transcribe(audio_path, vad_filter=settings.WHISPER_VAD_FILTER)
        transcript = "\n".join(_plain_lines(segments)).strip()
        logger.info("get_transcript.whisper_fallback_success", video_url=video_url)
        return ("whisper", transcript)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
        logger.info("get_transcript.cleanup_complete", video_url=video_url)
