"""Transcript pipeline: yt-dlp manual/auto subtitles, then Whisper fallback."""

import shutil
import subprocess
from pathlib import Path
from tempfile import mkdtemp

from faster_whisper import WhisperModel
import structlog

from app.config import settings

logger = structlog.get_logger()


class NoSubtitlesError(Exception):
    """Raised when no manual or auto subtitles are available for the video."""


def _seconds_to_vtt_ts(seconds: float) -> str:
    """Format seconds as VTT timestamp HH:MM:SS.mmm."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def get_transcript(video_url: str) -> tuple[str, str]:
    """Return (source, vtt_content). Raises NoSubtitlesError if no subtitles available."""
    logger.info("get_transcript.start", video_url=video_url)
    temp_dir = mkdtemp()
    try:
        out_base = str(Path(temp_dir) / "subs")
        # Try manual subtitles first.
        logger.info("get_transcript.try_manual_subtitles", video_url=video_url)
        subprocess.run(
            [
                "yt-dlp",
                "--match-filter",
                "duration>60",
                "--write-sub",
                "--skip-download",
                "--output",
                out_base,
                video_url,
            ],
            capture_output=True,
        )
        vtt_files = list(Path(temp_dir).glob("*.vtt"))
        if vtt_files:
            logger.info("get_transcript.manual_subtitles_found", video_url=video_url)
            return ("manual", vtt_files[0].read_text())

        # Try auto-generated subtitles.
        logger.info("get_transcript.try_auto_subtitles", video_url=video_url)
        subprocess.run(
            [
                "yt-dlp",
                "--match-filter",
                "duration>60",
                "--write-auto-sub",
                "--skip-download",
                "--output",
                out_base,
                video_url,
            ],
            capture_output=True,
        )
        vtt_files = list(Path(temp_dir).glob("*.vtt"))
        if vtt_files:
            logger.info("get_transcript.auto_subtitles_found", video_url=video_url)
            return ("auto", vtt_files[0].read_text())

        # Whisper fallback: download audio with yt-dlp -x, transcribe with faster-whisper, return vtt text.
        logger.info("get_transcript.whisper_fallback_start", video_url=video_url)
        audio_out = str(Path(temp_dir) / "audio_%(id)s.%(ext)s")
        subprocess.run(
            [
                "yt-dlp",
                "--match-filter",
                "duration>60",
                "-x",
                "--audio-format",
                "mp3",
                "--output",
                audio_out,
                video_url,
            ],
            capture_output=True,
        )
        mp3_files = list(Path(temp_dir).glob("*.mp3"))
        if not mp3_files:
            logger.error(
                "get_transcript.no_audio_downloaded_for_whisper",
                video_url=video_url,
            )
            raise NoSubtitlesError("No manual or auto subtitles available for this video")
        audio_path = str(mp3_files[0])
        model_path_or_name = settings.WHISPER_MODEL.strip()
        project_root = Path(__file__).resolve().parent.parent
        resolved_path = (
            (project_root / model_path_or_name).resolve()
            if not Path(model_path_or_name).is_absolute()
            else Path(model_path_or_name)
        )
        model_kwargs: dict = {"compute_type": settings.WHISPER_COMPUTE_TYPE}
        if resolved_path.is_dir() and (resolved_path / "model.bin").exists():
            model_kwargs["local_files_only"] = True
            model = WhisperModel(str(resolved_path), **model_kwargs)
        else:
            if settings.WHISPER_DOWNLOAD_ROOT:
                model_kwargs["download_root"] = settings.WHISPER_DOWNLOAD_ROOT
            model = WhisperModel(model_path_or_name, **model_kwargs)
        segments, _ = model.transcribe(audio_path)
        vtt_lines = ["WEBVTT", ""]
        for seg in segments:
            if not seg.text.strip():
                continue
            vtt_lines.append(
                f"{_seconds_to_vtt_ts(seg.start)} --> {_seconds_to_vtt_ts(seg.end)}"
            )
            vtt_lines.append(seg.text.strip())
            vtt_lines.append("")
        logger.info("get_transcript.whisper_fallback_success", video_url=video_url)
        return ("whisper", "\n".join(vtt_lines).strip())
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
        logger.info("get_transcript.cleanup_complete", video_url=video_url)
