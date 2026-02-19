"""Transcript pipeline: yt-dlp manual/auto subtitles, then Whisper fallback."""

import shutil
import subprocess
from pathlib import Path
from tempfile import mkdtemp


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

        raise NoSubtitlesError("No manual or auto subtitles available for this video")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
