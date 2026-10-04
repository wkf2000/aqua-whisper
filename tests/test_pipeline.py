"""Tests for transcript pipeline (get_transcript). Mock subprocess/yt-dlp."""

import json
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.config import settings
from app.pipeline import (
    NoSubtitlesError,
    UnsupportedLiveStatusError,
    VideoTooShortError,
    get_transcript,
)
from app.whisper import clear_model_cache


@pytest.fixture(autouse=True)
def _reset_model_cache() -> Iterator[None]:
    """Each test gets a fresh (mocked) model load."""
    clear_model_cache()
    yield
    clear_model_cache()


def _ok(stdout: bytes = b"") -> MagicMock:
    return MagicMock(returncode=0, stdout=stdout)


def _is_info_call(cmd: list[str]) -> bool:
    """True when cmd is the metadata precheck (--dump-single-json)."""
    return "--dump-single-json" in cmd


def _info(
    duration: object = 300,
    live_status: object = "not_live",
    title: object = None,
    channel: object = None,
    upload_date: object = None,
    language: object = None,
) -> MagicMock:
    """Mocked yt-dlp metadata JSON for the precheck call."""
    payload: dict[str, object] = {
        "duration": duration,
        "title": title,
        "channel": channel,
        "upload_date": upload_date,
        "language": language,
    }
    if live_status is not None:
        payload["live_status"] = live_status
    return MagicMock(returncode=0, stdout=json.dumps(payload).encode())


def _make_segment(start: float, end: float, text: str) -> object:
    """Minimal segment-like object for mocking faster_whisper."""
    return type("Segment", (), {"start": start, "end": end, "text": text})()


def test_manual_subtitle_returns_manual_and_plain_text(tmp_path: Path) -> None:
    """When yt-dlp (mocked) writes a manual .vtt, plain text is returned without markup."""
    vtt_body = "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nmanual line"

    def run_effect(cmd: list[str], **kwargs: object) -> MagicMock:
        if _is_info_call(cmd):
            return _info()
        if "--write-sub" in cmd and "--write-auto-sub" not in cmd:
            idx = cmd.index("--output")
            out_base = cmd[idx + 1]
            Path(out_base + ".en.vtt").write_text(vtt_body)
        return _ok()

    with (
        patch("app.pipeline.mkdtemp", return_value=str(tmp_path)),
        patch("app.pipeline.subprocess.run", side_effect=run_effect),
    ):
        source, content, _meta = get_transcript("https://www.youtube.com/watch?v=abc")
    assert source == "manual"
    assert content == "manual line"
    assert "WEBVTT" not in content


def test_manual_subtitle_uses_configured_sub_langs(tmp_path: Path) -> None:
    """Manual subtitle download passes --sub-langs for the configured language."""
    seen: list[list[str]] = []

    def run_effect(cmd: list[str], **kwargs: object) -> MagicMock:
        seen.append(cmd)
        if _is_info_call(cmd):
            return _info()
        if "--write-sub" in cmd and "--write-auto-sub" not in cmd:
            idx = cmd.index("--output")
            Path(cmd[idx + 1] + ".en.vtt").write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\na")
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
    """When only the original-language auto .vtt exists, get_transcript returns ('auto', text)."""
    vtt_body = "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nauto line"

    call_count = 0

    def run_effect(cmd: list[str], **kwargs: object) -> MagicMock:
        nonlocal call_count
        call_count += 1
        if _is_info_call(cmd):
            return _info()
        if "--write-auto-sub" in cmd:
            idx = cmd.index("--output")
            out_base = cmd[idx + 1]
            Path(out_base + ".en-orig.vtt").write_text(vtt_body)
        return _ok()

    with (
        patch("app.pipeline.mkdtemp", return_value=str(tmp_path)),
        patch("app.pipeline.subprocess.run", side_effect=run_effect),
    ):
        source, content, _meta = get_transcript("https://www.youtube.com/watch?v=xyz")
    assert source == "auto"
    assert content == "auto line"


def test_auto_subtitle_download_requests_original_language_track(tmp_path: Path) -> None:
    """The auto-caption call asks yt-dlp for the original-language '-orig' track only."""
    seen: list[list[str]] = []

    def run_effect(cmd: list[str], **kwargs: object) -> MagicMock:
        seen.append(cmd)
        if _is_info_call(cmd):
            return _info()
        return _ok()

    with (
        patch("app.pipeline.mkdtemp", return_value=str(tmp_path)),
        patch("app.pipeline.subprocess.run", side_effect=run_effect),
    ):
        with pytest.raises(NoSubtitlesError):
            get_transcript("https://www.youtube.com/watch?v=abc")

    auto_calls = [c for c in seen if "--write-auto-sub" in c]
    assert auto_calls, "expected an auto-caption download call"
    assert auto_calls[0][auto_calls[0].index("--sub-langs") + 1] == ".*-orig"


def test_original_auto_track_beats_manual_subtitle_in_another_language(
    tmp_path: Path,
) -> None:
    """A Chinese video with uploaded English subtitles still yields Chinese text.

    The '-orig' track is generated from the original audio, so it wins over a
    manual subtitle in a different (translated) language.
    """
    zh_body = "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\n中文内容"

    def run_effect(cmd: list[str], **kwargs: object) -> MagicMock:
        if _is_info_call(cmd):
            return _info(language="zh-Hans")
        if "--write-auto-sub" in cmd:
            out_base = cmd[cmd.index("--output") + 1]
            Path(out_base + ".zh-Hans-orig.vtt").write_text(zh_body)
        elif "--write-sub" in cmd:
            out_base = cmd[cmd.index("--output") + 1]
            Path(out_base + ".en.vtt").write_text(
                "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nenglish content"
            )
        return _ok()

    with (
        patch("app.pipeline.mkdtemp", return_value=str(tmp_path)),
        patch("app.pipeline.subprocess.run", side_effect=run_effect),
    ):
        source, content, _meta = get_transcript("https://www.youtube.com/watch?v=zh")
    assert source == "auto"
    assert content == "中文内容"


def test_manual_subtitle_in_original_language_beats_asr_track(tmp_path: Path) -> None:
    """A manual subtitle in the same language as the '-orig' track wins on quality."""
    manual_body = "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\n人工字幕"
    asr_body = "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\n机器字幕"

    def run_effect(cmd: list[str], **kwargs: object) -> MagicMock:
        if _is_info_call(cmd):
            return _info(language="zh-Hans")
        if "--write-auto-sub" in cmd:
            out_base = cmd[cmd.index("--output") + 1]
            Path(out_base + ".zh-Hans-orig.vtt").write_text(asr_body)
        elif "--write-sub" in cmd:
            out_base = cmd[cmd.index("--output") + 1]
            Path(out_base + ".zh-Hans.vtt").write_text(manual_body)
        return _ok()

    with (
        patch("app.pipeline.mkdtemp", return_value=str(tmp_path)),
        patch("app.pipeline.subprocess.run", side_effect=run_effect),
    ):
        source, content, _meta = get_transcript("https://www.youtube.com/watch?v=zh")
    assert source == "manual"
    assert content == "人工字幕"


def test_configured_language_order_decides_between_manual_tracks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With manual subtitles in several languages, the first configured match wins."""
    monkeypatch.setattr(settings, "SUBTITLE_LANGS", "zh.*,en")

    def run_effect(cmd: list[str], **kwargs: object) -> MagicMock:
        if _is_info_call(cmd):
            return _info()
        if "--write-sub" in cmd and "--write-auto-sub" not in cmd:
            out_base = cmd[cmd.index("--output") + 1]
            Path(out_base + ".en.vtt").write_text(
                "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nenglish"
            )
            Path(out_base + ".zh-Hans.vtt").write_text(
                "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n中文"
            )
        return _ok()

    with (
        patch("app.pipeline.mkdtemp", return_value=str(tmp_path)),
        patch("app.pipeline.subprocess.run", side_effect=run_effect),
    ):
        source, content, _meta = get_transcript("https://www.youtube.com/watch?v=multi")
    assert source == "manual"
    assert content == "中文"


def test_single_orig_track_without_language_report_is_used(tmp_path: Path) -> None:
    """When yt-dlp reports no original language, a single '-orig' track is trusted."""
    zh_body = "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\n中文内容"

    def run_effect(cmd: list[str], **kwargs: object) -> MagicMock:
        if _is_info_call(cmd):
            return _info()
        if "--write-auto-sub" in cmd:
            out_base = cmd[cmd.index("--output") + 1]
            Path(out_base + ".zh-Hans-orig.vtt").write_text(zh_body)
        return _ok()

    with (
        patch("app.pipeline.mkdtemp", return_value=str(tmp_path)),
        patch("app.pipeline.subprocess.run", side_effect=run_effect),
    ):
        source, content, _meta = get_transcript("https://www.youtube.com/watch?v=zh")
    assert source == "auto"
    assert content == "中文内容"


def test_multi_audio_orig_tracks_need_language_match(tmp_path: Path) -> None:
    """Dubbed '-orig' tracks that do not match the reported original audio are ignored."""
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    def run_effect(cmd: list[str], **kwargs: object) -> MagicMock:
        if _is_info_call(cmd):
            return _info(language="en-US")
        if "--write-auto-sub" in cmd:
            out_base = cmd[cmd.index("--output") + 1]
            Path(out_base + ".ar-orig.vtt").write_text(
                "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nعربى"
            )
            Path(out_base + ".bn-orig.vtt").write_text(
                "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nবাংলা"
            )
            return _ok()
        if "-f" in cmd:
            idx = cmd.index("--output")
            out_dir = Path(cmd[idx + 1]).parent
            (out_dir / "audio_abc.m4a").write_bytes(b"fake_audio")
        return _ok()

    mock_segments = [_make_segment(0.0, 2.5, "english default audio")]
    with (
        patch("app.pipeline.mkdtemp", return_value=str(work_dir)),
        patch("app.pipeline.subprocess.run", side_effect=run_effect),
        patch("app.whisper.WhisperModel") as mock_model_cls,
    ):
        mock_model_cls.return_value.transcribe.return_value = (mock_segments, None)
        source, content, _meta = get_transcript("https://www.youtube.com/watch?v=dub")
    assert source == "whisper"
    assert content == "english default audio"


def test_multi_audio_orig_track_matching_language_is_used(tmp_path: Path) -> None:
    """Among several '-orig' tracks, the one matching the reported language wins."""

    def run_effect(cmd: list[str], **kwargs: object) -> MagicMock:
        if _is_info_call(cmd):
            return _info(language="en-US")
        if "--write-auto-sub" in cmd:
            out_base = cmd[cmd.index("--output") + 1]
            Path(out_base + ".en-orig.vtt").write_text(
                "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nenglish original"
            )
            Path(out_base + ".ar-orig.vtt").write_text(
                "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nعربى"
            )
        return _ok()

    with (
        patch("app.pipeline.mkdtemp", return_value=str(tmp_path)),
        patch("app.pipeline.subprocess.run", side_effect=run_effect),
    ):
        source, content, _meta = get_transcript("https://www.youtube.com/watch?v=dub")
    assert source == "auto"
    assert content == "english original"


def test_vtt_header_and_inline_tags_stripped(tmp_path: Path) -> None:
    """Auto-caption VTT headers and word-level inline tags never reach the transcript."""
    vtt_body = (
        "WEBVTT\n"
        "Kind: captions\n"
        "Language: zh-Hans\n\n"
        "00:00:00.000 --> 00:00:02.000 align:start position:0%\n"
        "今<00:00:00.500><c>日</c>天<00:00:01.000><c>气</c>\n"
    )

    def run_effect(cmd: list[str], **kwargs: object) -> MagicMock:
        if _is_info_call(cmd):
            return _info()
        if "--write-sub" in cmd and "--write-auto-sub" not in cmd:
            out_base = cmd[cmd.index("--output") + 1]
            Path(out_base + ".zh-Hans.vtt").write_text(vtt_body)
        return _ok()

    with (
        patch("app.pipeline.mkdtemp", return_value=str(tmp_path)),
        patch("app.pipeline.subprocess.run", side_effect=run_effect),
    ):
        source, content, _meta = get_transcript("https://www.youtube.com/watch?v=tags")
    assert source == "manual"
    assert content == "今日天气"


def test_progress_reports_subtitle_stage(tmp_path: Path) -> None:
    """The progress callback receives one stage code on the subtitle path."""
    stages: list[str] = []
    vtt_body = "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nline"

    def run_effect(cmd: list[str], **kwargs: object) -> MagicMock:
        if _is_info_call(cmd):
            return _info()
        if "--write-sub" in cmd and "--write-auto-sub" not in cmd:
            out_base = cmd[cmd.index("--output") + 1]
            Path(out_base + ".en.vtt").write_text(vtt_body)
        return _ok()

    with (
        patch("app.pipeline.mkdtemp", return_value=str(tmp_path)),
        patch("app.pipeline.subprocess.run", side_effect=run_effect),
    ):
        _source, _content, _meta = get_transcript(
            "https://www.youtube.com/watch?v=prog", progress=stages.append
        )
    assert stages == ["downloading_subtitles"]


def test_progress_reports_whisper_stages(tmp_path: Path) -> None:
    """The progress callback receives every stage code on the Whisper path."""
    stages: list[str] = []
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    def run_effect(cmd: list[str], **kwargs: object) -> MagicMock:
        if _is_info_call(cmd):
            return _info()
        if "--write-sub" in cmd or "--write-auto-sub" in cmd:
            return MagicMock(returncode=1, stdout=b"", stderr=b"HTTP Error 429: Too Many Requests")
        if "-f" in cmd:
            idx = cmd.index("--output")
            out_dir = Path(cmd[idx + 1]).parent
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "audio_abc.m4a").write_bytes(b"fake_audio")
        return _ok()

    mock_segments = [_make_segment(0.0, 2.5, "whisper line")]
    with (
        patch("app.pipeline.mkdtemp", return_value=str(work_dir)),
        patch("app.pipeline.subprocess.run", side_effect=run_effect),
        patch("app.whisper.WhisperModel") as mock_model_cls,
    ):
        mock_model_cls.return_value.transcribe.return_value = (mock_segments, None)
        source, _content, _meta = get_transcript(
            "https://www.youtube.com/watch?v=prog", progress=stages.append
        )
    assert source == "whisper"
    assert stages == ["downloading_subtitles", "downloading_audio", "transcribing_audio"]


def test_manual_subtitle_429_falls_back_to_auto(tmp_path: Path) -> None:
    """A failed manual-subtitle download (HTTP 429) falls through to auto subtitles."""
    vtt_body = "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nauto line"

    def run_effect(cmd: list[str], **kwargs: object) -> MagicMock:
        if _is_info_call(cmd):
            return _info()
        if "--write-sub" in cmd and "--write-auto-sub" not in cmd:
            return MagicMock(
                returncode=1,
                stdout=b"",
                stderr=b"HTTP Error 429: Too Many Requests",
            )
        if "--write-auto-sub" in cmd:
            idx = cmd.index("--output")
            Path(cmd[idx + 1] + ".en-orig.vtt").write_text(vtt_body)
        return _ok()

    with (
        patch("app.pipeline.mkdtemp", return_value=str(tmp_path)),
        patch("app.pipeline.subprocess.run", side_effect=run_effect),
    ):
        source, content, _meta = get_transcript("https://www.youtube.com/watch?v=xyz")
    assert source == "auto"
    assert content == "auto line"


def test_subtitle_download_429_falls_back_to_whisper(tmp_path: Path) -> None:
    """When both subtitle downloads fail (HTTP 429), Whisper is tried instead of failing."""
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    def run_effect(cmd: list[str], **kwargs: object) -> MagicMock:
        if _is_info_call(cmd):
            return _info()
        if "--write-sub" in cmd or "--write-auto-sub" in cmd:
            return MagicMock(
                returncode=1,
                stdout=b"",
                stderr=b"HTTP Error 429: Too Many Requests",
            )
        # Last resort: audio download for Whisper must still be attempted.
        assert "-f" in cmd
        idx = cmd.index("--output")
        out_dir = Path(cmd[idx + 1]).parent
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "audio_abc.m4a").write_bytes(b"fake_audio")
        return _ok()

    mock_segments = [_make_segment(0.0, 2.5, "whisper fallback line")]
    with (
        patch("app.pipeline.mkdtemp", return_value=str(work_dir)),
        patch("app.pipeline.subprocess.run", side_effect=run_effect),
        patch("app.whisper.WhisperModel") as mock_model_cls,
    ):
        mock_model_cls.return_value.transcribe.return_value = (mock_segments, None)
        source, content, _meta = get_transcript("https://www.youtube.com/watch?v=abc")

    assert source == "whisper"
    assert content == "whisper fallback line"


def test_duplicate_caption_lines_collapsed(tmp_path: Path) -> None:
    """Rolling captions with consecutive repeated lines collapse to one line."""
    vtt_body = (
        "WEBVTT\n\n"
        "00:00:00.000 --> 00:00:01.000\nrolling caption\n\n"
        "00:00:01.000 --> 00:00:02.000\nrolling caption"
    )

    def run_effect(cmd: list[str], **kwargs: object) -> MagicMock:
        if _is_info_call(cmd):
            return _info()
        if "--write-sub" in cmd:
            idx = cmd.index("--output")
            Path(cmd[idx + 1] + ".en.vtt").write_text(vtt_body)
        return _ok()

    with (
        patch("app.pipeline.mkdtemp", return_value=str(tmp_path)),
        patch("app.pipeline.subprocess.run", side_effect=run_effect),
    ):
        _source, content, _meta = get_transcript("https://www.youtube.com/watch?v=dup")
    assert content == "rolling caption"


def test_whisper_fallback_when_no_manual_or_auto_returns_whisper_plain_text(
    tmp_path: Path,
) -> None:
    """When neither manual nor auto subs exist, audio is downloaded and Whisper runs."""
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    run_calls: list[list[str]] = []

    def run_effect(cmd: list[str], **kwargs: object) -> MagicMock:
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
        source, content, _meta = get_transcript("https://www.youtube.com/watch?v=abc")

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

    def run_effect(cmd: list[str], **kwargs: object) -> MagicMock:
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

    def run_effect(cmd: list[str], **kwargs: object) -> MagicMock:
        if _is_info_call(cmd):
            return _info(live_status="was_live")
        if "--write-sub" in cmd:
            Path(cmd[cmd.index("--output") + 1] + ".en.vtt").write_text(vtt_body)
        return _ok()

    with (
        patch("app.pipeline.mkdtemp", return_value=str(tmp_path)),
        patch("app.pipeline.subprocess.run", side_effect=run_effect),
    ):
        source, content, _meta = get_transcript("https://www.youtube.com/watch?v=past")
    assert source == "manual"
    assert content == "past stream line"


@pytest.mark.parametrize("live_status", ["is_live", "is_upcoming", "post_live", None])
def test_unsupported_live_status_is_skipped(tmp_path: Path, live_status: str | None) -> None:
    """Ongoing, upcoming, post-live and unknown statuses are skipped before any download."""
    run_calls: list[list[str]] = []

    def run_effect(cmd: list[str], **kwargs: object) -> MagicMock:
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
    """When every strategy fails (incl. the last-resort audio download), it surfaces."""

    def run_effect(cmd: list[str], **kwargs: object) -> MagicMock:
        if _is_info_call(cmd):
            return _info()
        return MagicMock(returncode=2, stdout=b"", stderr=b"boom")

    with (
        patch("app.pipeline.mkdtemp", return_value=str(tmp_path)),
        patch("app.pipeline.subprocess.run", side_effect=run_effect),
    ):
        with pytest.raises(RuntimeError, match="exit code 2"):
            get_transcript("https://www.youtube.com/watch?v=abc")


def test_metadata_extracted_from_probe_info(tmp_path: Path) -> None:
    """Video metadata from the probe is returned, with upload_date normalized to ISO."""
    vtt_body = "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nmeta line"

    def run_effect(cmd: list[str], **kwargs: object) -> MagicMock:
        if _is_info_call(cmd):
            return _info(title="A Talk", channel="Some Channel", upload_date="20260101")
        if "--write-sub" in cmd:
            Path(cmd[cmd.index("--output") + 1] + ".en.vtt").write_text(vtt_body)
        return _ok()

    with (
        patch("app.pipeline.mkdtemp", return_value=str(tmp_path)),
        patch("app.pipeline.subprocess.run", side_effect=run_effect),
    ):
        _source, _content, meta = get_transcript("https://www.youtube.com/watch?v=meta")

    assert meta.title == "A Talk"
    assert meta.channel == "Some Channel"
    assert meta.duration == 300
    assert meta.upload_date == "2026-01-01"


def test_metadata_falls_back_to_uploader_when_channel_missing(tmp_path: Path) -> None:
    """When yt-dlp has no channel field, the uploader is used; absent fields are None."""
    info = {"duration": 300, "live_status": "not_live", "uploader": "Uploader Name"}
    vtt_body = "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nline"

    def run_effect(cmd: list[str], **kwargs: object) -> MagicMock:
        if _is_info_call(cmd):
            return MagicMock(returncode=0, stdout=json.dumps(info).encode())
        if "--write-sub" in cmd:
            Path(cmd[cmd.index("--output") + 1] + ".en.vtt").write_text(vtt_body)
        return _ok()

    with (
        patch("app.pipeline.mkdtemp", return_value=str(tmp_path)),
        patch("app.pipeline.subprocess.run", side_effect=run_effect),
    ):
        _source, _content, meta = get_transcript("https://www.youtube.com/watch?v=upl")

    assert meta.channel == "Uploader Name"
    assert meta.title is None
    assert meta.upload_date is None
