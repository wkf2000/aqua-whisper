"""Tests for downloadable URL validation (YouTube and X.com)."""

from app.sources import is_downloadable_url, is_x_url


def test_youtube_watch_url_is_downloadable() -> None:
    """youtube.com watch URLs are accepted."""
    assert is_downloadable_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ") is True


def test_x_url_is_downloadable() -> None:
    """x.com post URLs are accepted."""
    assert is_downloadable_url("https://x.com/user/status/123") is True


def test_twitter_url_is_downloadable() -> None:
    """twitter.com post URLs are accepted."""
    assert is_downloadable_url("https://twitter.com/user/status/123") is True


def test_mobile_twitter_url_is_downloadable() -> None:
    """mobile.twitter.com post URLs are accepted."""
    assert is_downloadable_url("https://mobile.twitter.com/user/status/123") is True


def test_x_url_without_scheme_is_not_downloadable() -> None:
    """An x.com path without a scheme is rejected."""
    assert is_downloadable_url("x.com/user/status/123") is False


def test_vimeo_url_is_not_downloadable() -> None:
    """vimeo.com is not a supported download source."""
    assert is_downloadable_url("https://vimeo.com/123456789") is False


def test_empty_string_is_not_downloadable() -> None:
    """Empty string returns False."""
    assert is_downloadable_url("") is False


def test_is_x_url_rejects_lookalike_hosts() -> None:
    """Hosts that merely contain 'x.com' are rejected."""
    assert is_x_url("https://notx.com/user/status/1") is False
    assert is_x_url("https://x.com.evil.com/user/status/1") is False
