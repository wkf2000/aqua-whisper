"""Tests for transcript pipeline (get_transcript). Mock subprocess/yt-dlp."""

from pathlib import Path
from unittest.mock import MagicMock, patch


from app.pipeline import get_transcript


def _make_segment(start: float, end: float, text: str) -> object:
    """Minimal segment-like object for mocking faster_whisper."""
    return type("Segment", (), {"start": start, "end": end, "text": text})()


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


def test_whisper_fallback_when_no_manual_or_auto_returns_whisper_and_vtt(tmp_path: Path) -> None:
    """When neither manual nor auto subs exist, pipeline runs yt-dlp -x and whisper, returns ('whisper', vtt_content)."""
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    run_calls: list[list] = []

    def run_effect(cmd: list, **kwargs: object) -> MagicMock:
        run_calls.append(cmd)
        # Manual/auto: no .vtt
        if "--write-sub" in cmd or "--write-auto-sub" in cmd:
            return MagicMock(returncode=0)
        # yt-dlp -x: create fake .mp3 in output dir
        if "-x" in cmd and "--audio-format" in cmd:
            out_idx = cmd.index("--output")
            out_tpl = cmd[out_idx + 1]
            out_dir = Path(out_tpl).parent
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "audio_abc.mp3").write_bytes(b"fake_audio")
            return MagicMock(returncode=0)
        return MagicMock(returncode=0)

    mock_segments = [_make_segment(0.0, 2.5, "whisper fallback line")]
    with (
        patch("app.pipeline.mkdtemp", return_value=str(work_dir)),
        patch("app.pipeline.subprocess.run", side_effect=run_effect),
        patch("app.pipeline.WhisperModel") as mock_model_cls,
    ):
        mock_model_cls.return_value.transcribe.return_value = (mock_segments, None)
        source, content = get_transcript("https://www.youtube.com/watch?v=abc")

    assert source == "whisper"
    assert "WEBVTT" in content
    assert "whisper fallback line" in content
    # Should have called yt-dlp -x for audio download
    ytdlp_x_calls = [c for c in run_calls if "-x" in c and "mp3" in c]
    assert len(ytdlp_x_calls) >= 1
    # Cleanup: temp dir removed in try/finally
    assert not work_dir.exists()


def test_whisper_fallback_cleans_up_temp_dir(tmp_path: Path) -> None:
    """When whisper fallback runs, temp dir is removed in try/finally."""
    work_dir = tmp_path / "cleanup_check"
    work_dir.mkdir()

    def run_effect(cmd: list, **kwargs: object) -> MagicMock:
        if "--write-sub" in cmd or "--write-auto-sub" in cmd:
            return MagicMock(returncode=0)
        if "-x" in cmd and "--audio-format" in cmd:
            out_idx = cmd.index("--output")
            out_tpl = cmd[out_idx + 1]
            out_dir = Path(out_tpl).parent
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "audio_xyz.mp3").write_bytes(b"fake")
            return MagicMock(returncode=0)
        return MagicMock(returncode=0)

    mock_segments = [_make_segment(0.0, 1.0, "cleanup test")]
    with (
        patch("app.pipeline.mkdtemp", return_value=str(work_dir)),
        patch("app.pipeline.subprocess.run", side_effect=run_effect),
        patch("app.pipeline.WhisperModel") as mock_model_cls,
    ):
        mock_model_cls.return_value.transcribe.return_value = (mock_segments, None)
        get_transcript("https://www.youtube.com/watch?v=xyz")

    assert not work_dir.exists(), "Temp dir should be removed after get_transcript"
