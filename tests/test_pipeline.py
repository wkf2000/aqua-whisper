"""Tests for transcript pipeline (get_transcript). Mock subprocess/yt-dlp."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.pipeline import NoSubtitlesError, get_transcript


def test_manual_subtitle_returns_manual_and_vtt_content(tmp_path: Path) -> None:
    """When yt-dlp (mocked) writes manual .vtt, get_transcript returns ('manual', vtt_body)."""
    vtt_body = "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nmanual line"

    def run_effect(cmd: list, **kwargs: object) -> MagicMock:
        if "--write-sub" in cmd and "--write-auto-sub" not in cmd:
            idx = cmd.index("--output")
            out_base = cmd[idx + 1]
            Path(out_base + ".vtt").write_text(vtt_body)
        return MagicMock(returncode=0)

    with (
        patch("app.pipeline.mkdtemp", return_value=str(tmp_path)),
        patch("app.pipeline.subprocess.run", side_effect=run_effect),
    ):
        source, content = get_transcript("https://www.youtube.com/watch?v=abc")
    assert source == "manual"
    assert content == vtt_body


def test_auto_subtitle_when_no_manual_returns_auto_and_vtt_content(tmp_path: Path) -> None:
    """When only auto .vtt exists (no manual), get_transcript returns ('auto', vtt_body)."""
    vtt_body = "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nauto line"

    call_count = 0

    def run_effect(cmd: list, **kwargs: object) -> MagicMock:
        nonlocal call_count
        call_count += 1
        if "--write-auto-sub" in cmd:
            idx = cmd.index("--output")
            out_base = cmd[idx + 1]
            Path(out_base + ".vtt").write_text(vtt_body)
        return MagicMock(returncode=0)

    with (
        patch("app.pipeline.mkdtemp", return_value=str(tmp_path)),
        patch("app.pipeline.subprocess.run", side_effect=run_effect),
    ):
        source, content = get_transcript("https://www.youtube.com/watch?v=xyz")
    assert source == "auto"
    assert content == vtt_body


def test_no_subtitles_raises(tmp_path: Path) -> None:
    """When neither manual nor auto .vtt exists, get_transcript raises NoSubtitlesError."""
    def run_effect(cmd: list, **kwargs: object) -> MagicMock:
        # Do not create any .vtt file
        return MagicMock(returncode=0)

    with (
        patch("app.pipeline.mkdtemp", return_value=str(tmp_path)),
        patch("app.pipeline.subprocess.run", side_effect=run_effect),
    ):
        with pytest.raises(NoSubtitlesError):
            get_transcript("https://www.youtube.com/watch?v=none")