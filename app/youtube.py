"""YouTube URL validation."""

import re

# Allow youtube.com (with optional www.) and youtu.be
_YOUTUBE_HOST_PATTERN = re.compile(
    r"^https?://(www\.)?(youtube\.com|youtu\.be)/",
    re.IGNORECASE,
)


def is_youtube_url(url: str) -> bool:
    """Return True if url is a valid YouTube URL (youtube.com or youtu.be), else False."""
    if not url or not url.strip():
        return False
    return bool(_YOUTUBE_HOST_PATTERN.match(url.strip()))
