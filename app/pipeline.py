"""Transcript pipeline: yt-dlp manual/auto subtitles, then Whisper fallback."""

import shutil
import subprocess
from pathlib import Path
from tempfile import mkdtemp

from faster_whisper import WhisperModel
from faster_whisper.utils import format_timestamp


class NoSubtitlesError(Exception):
    """Raised when no manual or auto subtitles are available for the video."""


def get_transcript(video_url: str) -> tuple[str, str]:
    """Return (source, vtt_content). Raises NoSubtitlesError if no subtitles available."""
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
            return ("manual", vtt_files[0].read_text())

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
            return ("auto", vtt_files[0].read_text())

        # Whisper fallback: download audio with yt-dlp -x, transcribe with faster-whisper, return VTT.
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
        model = WhisperModel("base")
        segments, _ = model.transcribe(audio_path)
        vtt_lines = ["WEBVTT", ""]
        for seg in segments:
            start_str = format_timestamp(seg.start, always_include_hours=True, decimal_marker=".")
            end_str = format_timestamp(seg.end, always_include_hours=True, decimal_marker=".")
            vtt_lines.append(f"{start_str} --> {end_str}")
            vtt_lines.append(seg.text.strip())
            vtt_lines.append("")
        vtt_content = "\n".join(vtt_lines).strip()
        return ("whisper", vtt_content)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
