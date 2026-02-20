"""Transcript pipeline: yt-dlp manual/auto subtitles, then Whisper fallback."""

import re
import shutil
import subprocess
from pathlib import Path
from tempfile import mkdtemp

from faster_whisper import WhisperModel

from app.config import settings


class NoSubtitlesError(Exception):
    """Raised when no manual or auto subtitles are available for the video."""


# VTT timestamp line (e.g. "00:00:01.000 --> 00:00:04.000")
_VTT_TIMING = re.compile(r"^\d{2}:\d{2}:\d{2}\.\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}\.\d{3}")


def _vtt_to_plain_text(vtt: str) -> str:
    """Extract plain text from WEBVTT content (one line per cue)."""
    lines: list[str] = []
    for line in vtt.strip().splitlines():
        line = line.strip()
        if not line or line == "WEBVTT" or _VTT_TIMING.match(line) or line.isdigit():
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def get_transcript(video_url: str) -> tuple[str, str]:
    """Return (source, plain_text_content). Raises NoSubtitlesError if no subtitles available."""
    temp_dir = mkdtemp()
    try:
        out_base = str(Path(temp_dir) / "subs")
        # Try manual subtitles first.
        subprocess.run(
            ["yt-dlp", "--write-sub", "--skip-download", "--output", out_base, video_url],
            capture_output=True,
        )
        vtt_files = list(Path(temp_dir).glob("*.vtt"))
        if vtt_files:
            return ("manual", _vtt_to_plain_text(vtt_files[0].read_text()))

        # Try auto-generated subtitles.
        subprocess.run(
            [
                "yt-dlp",
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
            return ("auto", _vtt_to_plain_text(vtt_files[0].read_text()))

        # Whisper fallback: download audio with yt-dlp -x, transcribe with faster-whisper, return plain text.
        audio_out = str(Path(temp_dir) / "audio_%(id)s.%(ext)s")
        subprocess.run(
            [
                "yt-dlp",
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
            raise NoSubtitlesError("No manual or auto subtitles available for this video")
        audio_path = str(mp3_files[0])
        model_path_or_name = settings.WHISPER_MODEL.strip()
        project_root = Path(__file__).resolve().parent.parent
        resolved_path = (project_root / model_path_or_name).resolve() if not Path(model_path_or_name).is_absolute() else Path(model_path_or_name)
        model_kwargs: dict = {"compute_type": settings.WHISPER_COMPUTE_TYPE}
        if resolved_path.is_dir() and (resolved_path / "model.bin").exists():
            model_kwargs["local_files_only"] = True
            model = WhisperModel(str(resolved_path), **model_kwargs)
        else:
            if settings.WHISPER_DOWNLOAD_ROOT:
                model_kwargs["download_root"] = settings.WHISPER_DOWNLOAD_ROOT
            model = WhisperModel(model_path_or_name, **model_kwargs)
        segments, _ = model.transcribe(audio_path)
        plain_text = "\n".join(seg.text.strip() for seg in segments if seg.text.strip()).strip()
        return ("whisper", plain_text)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
