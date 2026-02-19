"""Tests for YouTube URL validation."""

from app.youtube import is_youtube_url


def test_valid_youtube_watch_url_returns_true() -> None:
    """https://www.youtube.com/watch?v=... is valid."""
    assert is_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ") is True


def test_valid_youtu_be_short_url_returns_true() -> None:
    """https://youtu.be/... is valid."""
    assert is_youtube_url("https://youtu.be/dQw4w9WgXcQ") is True


def test_vimeo_url_returns_false() -> None:
    """https://vimeo.com/... is not a YouTube URL."""
    assert is_youtube_url("https://vimeo.com/123456789") is False


def test_not_a_url_returns_false() -> None:
    """Plain string that is not a URL returns False."""
    assert is_youtube_url("not-a-url") is False


def test_empty_string_returns_false() -> None:
    """Empty string returns False."""
    assert is_youtube_url("") is False
