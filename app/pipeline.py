"""Transcript pipeline: yt-dlp manual/auto subtitles, then Whisper fallback.

Always returns plain text, in the video's original language: the auto captions
generated from the original audio (yt-dlp "-orig" tracks) are preferred over
machine-translated tracks and over manual subtitles in other languages. Manual
subtitles are fetched for the languages in SUBTITLE_LANGS, in that order.
Live/upcoming broadcasts and videos not longer than 60 seconds are rejected up
front with a clear error instead of the old misleading "no subtitles" one. A
failed subtitle download (e.g. YouTube HTTP 429 rate limiting) falls back to the
next strategy instead of failing the job.
"""

import json
import re
import shutil
import subprocess
from collections.abc import Iterable
from pathlib import Path
from tempfile import mkdtemp
from typing import Any, NamedTuple

import structlog
from faster_whisper import BatchedInferencePipeline

from app.config import settings
from app.whisper import get_model

logger = structlog.get_logger()

MIN_VIDEO_DURATION = 60

# Only finished videos can be transcribed: an ongoing, upcoming or still-processing
# broadcast ("is_live", "is_upcoming", "post_live") has no stable media to fetch.
ALLOWED_LIVE_STATUSES = frozenset({"not_live", "was_live"})

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

# yt-dlp labels the auto captions generated from the original audio with an
# "-orig" suffix (e.g. "zh-Hans-orig"); machine-translated tracks carry no
# marker. Fetching only the original track keeps the transcript in the video's
# own language instead of a translation such as English.
_ORIG_SUB_LANGS = ".*-orig"


class NoSubtitlesError(Exception):
    """Raised when no manual or auto subtitles are available for the video."""


class VideoTooShortError(Exception):
    """Raised when the video is not longer than MIN_VIDEO_DURATION seconds."""


class UnsupportedLiveStatusError(Exception):
    """Raised when the video's live broadcast status is not in ALLOWED_LIVE_STATUSES."""


class VideoMetadata(NamedTuple):
    """Browsable video metadata from the yt-dlp probe; missing fields are None."""

    title: str | None
    channel: str | None
    duration: float | None
    upload_date: str | None


def _extract_metadata(info: dict[str, Any]) -> VideoMetadata:
    """Pull browsable metadata from the yt-dlp info dict.

    yt-dlp reports upload_date as YYYYMMDD; it is normalized to ISO YYYY-MM-DD.
    The channel name falls back to the uploader when the channel field is absent.
    """
    upload_date = info.get("upload_date")
    if isinstance(upload_date, str) and len(upload_date) == 8 and upload_date.isdigit():
        upload_date = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}"
    return VideoMetadata(
        title=info.get("title"),
        channel=info.get("channel") or info.get("uploader"),
        duration=info.get("duration"),
        upload_date=upload_date,
    )


def _run(cmd: list[str], timeout: int) -> str:
    """Run a yt-dlp command and return its decoded stdout.

    Raises a clear error on non-zero exit or timeout instead of hanging the worker.
    """
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
    return result.stdout.decode("utf-8", "replace").strip()


def _download_subtitles(video_url: str, out_base: str, sub_flag: str, sub_langs: str) -> list[Path]:
    """Run one yt-dlp subtitle download and return the .vtt files it wrote.

    A failed download (e.g. HTTP 429 rate limiting when YouTube rejects
    non-impersonated requests) means "no subtitles from this source", not a
    failed job: [] is returned so the caller falls back to the next strategy.
    """
    try:
        _run(
            [
                "yt-dlp",
                "--match-filter",
                f"duration>{MIN_VIDEO_DURATION}",
                sub_flag,
                "--sub-langs",
                sub_langs,
                "--skip-download",
                "--output",
                out_base,
                video_url,
            ],
            _SUBTITLE_TIMEOUT,
        )
    except RuntimeError as exc:
        logger.warning(
            "get_transcript.subtitle_download_failed",
            video_url=video_url,
            mode=sub_flag,
            error=str(exc),
        )
        return []
    return list(Path(out_base).parent.glob("*.vtt"))


def _configured_sub_langs() -> list[str]:
    """Configured subtitle language patterns, in preference order."""
    return [lang.strip() for lang in settings.SUBTITLE_LANGS.split(",") if lang.strip()]


def _subtitle_lang(path: Path, out_base: str) -> str:
    """Language code from a '<out_base>.<lang>.vtt' subtitle filename, or ''."""
    prefix = f"{Path(out_base).name}."
    if not (path.name.startswith(prefix) and path.name.endswith(".vtt")):
        return ""
    return path.name[len(prefix) : -len(".vtt")]


def _base_lang(code: str) -> str:
    """Primary language part of a code: 'zh-Hans', 'zh-Hans-orig', 'en-US' -> base."""
    return code.split("-")[0].strip().lower()


def _pick_subtitle(files: list[Path], out_base: str, patterns: list[str]) -> Path | None:
    """First file whose language matches the earliest pattern.

    yt-dlp matches --sub-langs patterns with a case-insensitive fullmatch, and
    the caller must apply the same rule when several languages were downloaded.
    """
    for pattern in patterns:
        matcher = re.compile(pattern, re.IGNORECASE)
        for path in sorted(files):
            if matcher.fullmatch(_subtitle_lang(path, out_base)):
                return path
    return None


def _original_track(files: list[Path], out_base: str, language: str | None) -> Path | None:
    """Pick the '-orig' auto-caption track that matches the video's spoken language.

    Multi-audio videos have one '-orig' track per dubbed language, so when
    yt-dlp reports the original audio language, only a matching '-orig' track
    is trusted. Without that report, a single '-orig' track is used as-is and
    several tracks mean the original language cannot be told apart from dubs.
    """
    orig_files = [p for p in sorted(files) if _subtitle_lang(p, out_base).endswith("-orig")]
    if not orig_files:
        return None
    if language is not None:
        base = _base_lang(language)
        for path in orig_files:
            if _base_lang(_subtitle_lang(path, out_base)) == base:
                return path
        return None
    return orig_files[0] if len(orig_files) == 1 else None


def _dedupe(lines: Iterable[str]) -> list[str]:
    """Keep non-empty lines, collapsing consecutive duplicates (rolling captions)."""
    out: list[str] = []
    prev: str | None = None
    for raw in lines:
        line = raw.strip()
        if line and line != prev:
            out.append(line)
            prev = line
    return out


def _vtt_lines(vtt: str) -> list[str]:
    """Caption lines from a VTT file, excluding the header block and timestamp cues.

    Auto-generated captions also carry word-level inline markup
    (e.g. "<c>字</c>" and <00:00:02.919> tags); it is removed so the transcript
    and the LLM summary see plain text.
    """
    lines: list[str] = []
    in_cues = False
    for raw in vtt.splitlines():
        line = raw.strip()
        if "-->" in line:
            in_cues = True
            continue
        if not in_cues or not line:
            continue
        cleaned = re.sub(r"<[^>]+>", "", line).strip()
        if cleaned:
            lines.append(cleaned)
    return lines


def _vtt_to_plain_text(vtt: str) -> str:
    """Strip VTT markup and collapse consecutive duplicate caption lines."""
    return "\n".join(_dedupe(_vtt_lines(vtt)))


def _probe_video(video_url: str) -> dict[str, Any]:
    """Fetch video metadata up front with a single yt-dlp JSON call."""
    cmd = ["yt-dlp", "--skip-download", "--dump-single-json", video_url]
    stdout = _run(cmd, _SUBTITLE_TIMEOUT)
    try:
        info = json.loads(stdout)
    except ValueError as exc:
        raise RuntimeError(f"yt-dlp returned unparseable video info: {stdout[:200]!r}") from exc
    if not isinstance(info, dict):
        raise RuntimeError(f"yt-dlp returned unexpected video info: {stdout[:200]!r}")
    return info


def _check_live_status(info: dict[str, Any], video_url: str) -> None:
    """Reject anything that is not a finished video (live, upcoming, post-live, unknown)."""
    live_status = info.get("live_status")
    if live_status in ALLOWED_LIVE_STATUSES:
        logger.info("get_transcript.live_status_ok", video_url=video_url, live_status=live_status)
        return
    logger.warning(
        "get_transcript.skipped_live_status", video_url=video_url, live_status=live_status
    )
    raise UnsupportedLiveStatusError(
        f"Video live status {live_status!r} is not supported; only finished videos "
        f"({', '.join(sorted(ALLOWED_LIVE_STATUSES))}) are transcribed"
    )


def _check_duration(info: dict[str, Any]) -> None:
    """Reject videos not longer than MIN_VIDEO_DURATION."""
    # The JSON value type is unknown; float() still rejects bad values at runtime.
    raw_duration: Any = info.get("duration")
    try:
        duration = float(raw_duration)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"yt-dlp returned an unparseable duration: {raw_duration!r}") from exc
    if duration <= MIN_VIDEO_DURATION:
        raise VideoTooShortError(
            f"Video is {duration:.0f}s long; only videos longer than "
            f"{MIN_VIDEO_DURATION}s are supported"
        )


def get_transcript(video_url: str) -> tuple[str, str, VideoMetadata]:
    """Return (source, plain_text, metadata). Raises NoSubtitlesError if no transcript."""
    logger.info("get_transcript.start", video_url=video_url)
    info = _probe_video(video_url)
    _check_live_status(info, video_url)
    _check_duration(info)
    metadata = _extract_metadata(info)
    # yt-dlp reports the original audio language when it can tell it from the
    # captions or the audio tracks (e.g. "zh-Hans", "en-US"); None otherwise.
    original_language = info.get("language")
    if not isinstance(original_language, str) or not original_language.strip():
        original_language = None
    temp_dir = mkdtemp()
    try:
        out_base = str(Path(temp_dir) / "subs")

        # Manual subtitles in the configured languages; a failed download falls
        # back to the next strategy instead of failing the job.
        logger.info("get_transcript.try_manual_subtitles", video_url=video_url)
        manual_files = _download_subtitles(
            video_url, out_base, "--write-sub", settings.SUBTITLE_LANGS
        )
        manual_pick = _pick_subtitle(manual_files, out_base, _configured_sub_langs())
        if manual_pick is not None:
            logger.info(
                "get_transcript.manual_subtitles_found",
                video_url=video_url,
                language=_subtitle_lang(manual_pick, out_base),
            )

        # Auto captions in the video's own language, whatever that language is.
        logger.info("get_transcript.try_auto_subtitles", video_url=video_url)
        auto_files = _download_subtitles(video_url, out_base, "--write-auto-sub", _ORIG_SUB_LANGS)
        orig_pick = _original_track(auto_files, out_base, original_language)
        if orig_pick is not None:
            logger.info(
                "get_transcript.original_auto_subtitles_found",
                video_url=video_url,
                language=_subtitle_lang(orig_pick, out_base),
            )

        # The original-language track wins over a manual subtitle in another
        # language (a Chinese clip with uploaded English subtitles stays Chinese);
        # a manual subtitle in the same language wins on quality.
        if orig_pick is not None and (
            manual_pick is None
            or _base_lang(_subtitle_lang(manual_pick, out_base))
            != _base_lang(_subtitle_lang(orig_pick, out_base))
        ):
            return ("auto", _vtt_to_plain_text(orig_pick.read_text()), metadata)
        if manual_pick is not None:
            return ("manual", _vtt_to_plain_text(manual_pick.read_text()), metadata)

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
        transcript = "\n".join(_dedupe(getattr(seg, "text", "") for seg in segments))
        logger.info("get_transcript.whisper_fallback_success", video_url=video_url)
        return ("whisper", transcript, metadata)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
        logger.info("get_transcript.cleanup_complete", video_url=video_url)
