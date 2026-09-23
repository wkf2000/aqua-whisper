"""Tests for transcript pipeline (get_transcript). Mock subprocess/yt-dlp."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.config import settings
from app.pipeline import UnsupportedLiveStatusError, VideoTooShortError, get_transcript
from app.whisper import clear_model_cache


@pytest.fixture(autouse=True)
def _reset_model_cache() -> None:
    """Each test gets a fresh (mocked) model load."""
    clear_model_cache()
    yield
    clear_model_cache()


def _ok(stdout: bytes = b"") -> MagicMock:
    return MagicMock(returncode=0, stdout=stdout)


def _is_info_call(cmd: list) -> bool:
    """True when cmd is the metadata precheck (--dump-single-json)."""
    return "--dump-single-json" in cmd


def _info(duration: object = 300, live_status: object = "not_live") -> MagicMock:
    """Mocked yt-dlp metadata JSON for the precheck call."""
    payload: dict = {"duration": duration}
    if live_status is not None:
        payload["live_status"] = live_status
    return MagicMock(returncode=0, stdout=json.dumps(payload).encode())


def _make_segment(start: float, end: float, text: str) -> object:
    """Minimal segment-like object for mocking faster_whisper."""
    return type("Segment", (), {"start": start, "end": end, "text": text})()


def test_manual_subtitle_returns_manual_and_plain_text(tmp_path: Path) -> None:
    """When yt-dlp (mocked) writes a manual .vtt, plain text is returned without markup."""
    vtt_body = "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nmanual line"

    def run_effect(cmd: list, **kwargs: object) -> MagicMock:
        if _is_info_call(cmd):
            return _info()
        if "--write-sub" in cmd and "--write-auto-sub" not in cmd:
            idx = cmd.index("--output")
            out_base = cmd[idx + 1]
            Path(out_base + ".vtt").write_text(vtt_body)
        return _ok()

    with (
        patch("app.pipeline.mkdtemp", return_value=str(tmp_path)),
        patch("app.pipeline.subprocess.run", side_effect=run_effect),
    ):
        source, content = get_transcript("https://www.youtube.com/watch?v=abc")
    assert source == "manual"
    assert content == "manual line"
    assert "WEBVTT" not in content


def test_manual_subtitle_uses_configured_sub_langs(tmp_path: Path) -> None:
    """Manual subtitle download passes --sub-langs for the configured language."""
    seen: list[list] = []

    def run_effect(cmd: list, **kwargs: object) -> MagicMock:
        seen.append(cmd)
        if _is_info_call(cmd):
            return _info()
        if "--write-sub" in cmd and "--write-auto-sub" not in cmd:
            idx = cmd.index("--output")
            Path(cmd[idx + 1] + ".vtt").write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\na")
        return _ok()

    with (
        patch("app.pipeline.mkdtemp", return_value=str(tmp_path)),
        patch("app.pipeline.subprocess.run", side_effect=run_effect),
    ):
        get_transcript("https://www.youtube.com/watch?v=abc")
    manual_call = [c for c in seen if "--write-sub" in c][0]
    assert "--sub-langs" in manual_call
    assert manual_call[manual_call.index("--sub-langs") + 1] == settings.SUBTITLE_LANGS


def test_auto_subtitle_when_no_manual_returns_auto_and_plain_text(tmp_path: Path) -> None:
    """When only auto .vtt exists (no manual), get_transcript returns ('auto', text)."""
    vtt_body = "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nauto line"

    call_count = 0

    def run_effect(cmd: list, **kwargs: object) -> MagicMock:
        nonlocal call_count
        call_count += 1
        if _is_info_call(cmd):
            return _info()
        if "--write-auto-sub" in cmd:
            idx = cmd.index("--output")
            out_base = cmd[idx + 1]
            Path(out_base + ".vtt").write_text(vtt_body)
        return _ok()

    with (
        patch("app.pipeline.mkdtemp", return_value=str(tmp_path)),
        patch("app.pipeline.subprocess.run", side_effect=run_effect),
    ):
        source, content = get_transcript("https://www.youtube.com/watch?v=xyz")
    assert source == "auto"
    assert content == "auto line"


def test_duplicate_caption_lines_collapsed(tmp_path: Path) -> None:
    """Rolling captions with consecutive repeated lines collapse to one line."""
    vtt_body = (
        "WEBVTT\n\n"
        "00:00:00.000 --> 00:00:01.000\nrolling caption\n\n"
        "00:00:01.000 --> 00:00:02.000\nrolling caption"
    )

    def run_effect(cmd: list, **kwargs: object) -> MagicMock:
        if _is_info_call(cmd):
            return _info()
        if "--write-sub" in cmd:
            idx = cmd.index("--output")
            Path(cmd[idx + 1] + ".vtt").write_text(vtt_body)
        return _ok()

    with (
        patch("app.pipeline.mkdtemp", return_value=str(tmp_path)),
        patch("app.pipeline.subprocess.run", side_effect=run_effect),
    ):
        _source, content = get_transcript("https://www.youtube.com/watch?v=dup")
    assert content == "rolling caption"


def test_whisper_fallback_when_no_manual_or_auto_returns_whisper_plain_text(
    tmp_path: Path,
) -> None:
    """When neither manual nor auto subs exist, audio is downloaded and Whisper runs."""
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    run_calls: list[list] = []

    def run_effect(cmd: list, **kwargs: object) -> MagicMock:
        run_calls.append(cmd)
        if _is_info_call(cmd):
            return _info()
        if "--write-sub" in cmd or "--write-auto-sub" in cmd:
            return _ok()
        if "-f" in cmd and cmd[cmd.index("-f") + 1] == "ba/b":
            idx = cmd.index("--output")
            out_dir = Path(cmd[idx + 1]).parent
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "audio_abc.m4a").write_bytes(b"fake_audio")
            return _ok()
        return _ok()

    mock_segments = [_make_segment(0.0, 2.5, "whisper fallback line")]
    with (
        patch("app.pipeline.mkdtemp", return_value=str(work_dir)),
        patch("app.pipeline.subprocess.run", side_effect=run_effect),
        patch("app.whisper.WhisperModel") as mock_model_cls,
    ):
        mock_model_cls.return_value.transcribe.return_value = (mock_segments, None)
        source, content = get_transcript("https://www.youtube.com/watch?v=abc")

    assert source == "whisper"
    assert content == "whisper fallback line"
    assert "WEBVTT" not in content
    # Audio was fetched without an mp3 re-encode.
    audio_calls = [c for c in run_calls if "-f" in c]
    assert len(audio_calls) >= 1
    assert not any("--audio-format" in c for c in audio_calls)
    # Cleanup: temp dir removed in try/finally.
    assert not work_dir.exists()


def test_video_too_short_raises_clear_error(tmp_path: Path) -> None:
    """Videos not longer than 60s are rejected with a clear error."""

    def run_effect(cmd: list, **kwargs: object) -> MagicMock:
        if _is_info_call(cmd):
            return _info(duration=45)
        return _ok()

    with (
        patch("app.pipeline.mkdtemp", return_value=str(tmp_path)),
        patch("app.pipeline.subprocess.run", side_effect=run_effect),
    ):
        with pytest.raises(VideoTooShortError, match="45s"):
            get_transcript("https://www.youtube.com/watch?v=short")


def test_was_live_video_is_transcribed(tmp_path: Path) -> None:
    """A finished livestream (was_live) is processed like a regular video."""
    vtt_body = "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\npast stream line"

    def run_effect(cmd: list, **kwargs: object) -> MagicMock:
        if _is_info_call(cmd):
            return _info(live_status="was_live")
        if "--write-sub" in cmd:
            Path(cmd[cmd.index("--output") + 1] + ".vtt").write_text(vtt_body)
        return _ok()

    with (
        patch("app.pipeline.mkdtemp", return_value=str(tmp_path)),
        patch("app.pipeline.subprocess.run", side_effect=run_effect),
    ):
        source, content = get_transcript("https://www.youtube.com/watch?v=past")
    assert source == "manual"
    assert content == "past stream line"


@pytest.mark.parametrize("live_status", ["is_live", "is_upcoming", "post_live", None])
def test_unsupported_live_status_is_skipped(tmp_path: Path, live_status: str | None) -> None:
    """Ongoing, upcoming, post-live and unknown statuses are skipped before any download."""
    run_calls: list[list] = []

    def run_effect(cmd: list, **kwargs: object) -> MagicMock:
        run_calls.append(cmd)
        if _is_info_call(cmd):
            return _info(duration=None, live_status=live_status)
        return _ok()

    with (
        patch("app.pipeline.mkdtemp", return_value=str(tmp_path)),
        patch("app.pipeline.subprocess.run", side_effect=run_effect),
    ):
        with pytest.raises(UnsupportedLiveStatusError, match=str(live_status)):
            get_transcript("https://www.youtube.com/watch?v=live")

    # Only the metadata probe ran; no subtitle or audio download was attempted.
    assert len(run_calls) == 1


def test_ytdlp_failure_raises_clear_error(tmp_path: Path) -> None:
    """A non-zero yt-dlp exit raises a clear error instead of a silent fallthrough."""

    def run_effect(cmd: list, **kwargs: object) -> MagicMock:
        if _is_info_call(cmd):
            return _info()
        return MagicMock(returncode=2, stdout=b"", stderr=b"boom")

    with (
        patch("app.pipeline.mkdtemp", return_value=str(tmp_path)),
        patch("app.pipeline.subprocess.run", side_effect=run_effect),
    ):
        with pytest.raises(RuntimeError, match="exit code 2"):
            get_transcript("https://www.youtube.com/watch?v=abc")
