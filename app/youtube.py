"""YouTube URL validation and video id extraction."""

import re

# Allow youtube.com (with optional www.) and youtu.be
_YOUTUBE_HOST_PATTERN = re.compile(
    r"^https?://(www\.)?(youtube\.com|youtu\.be)/",
    re.IGNORECASE,
)

# watch?v=, youtu.be/, shorts/, embed/ forms of a video id
_VIDEO_ID_PATTERN = re.compile(
    r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|shorts/|embed/)|youtu\.be/)([\w-]{11})",
    re.IGNORECASE,
)


def is_youtube_url(url: str) -> bool:
    """Return True if url is a valid YouTube URL (youtube.com or youtu.be), else False."""
    if not url or not url.strip():
        return False
    return bool(_YOUTUBE_HOST_PATTERN.match(url.strip()))


def extract_video_id(url: str) -> str | None:
    """Return the 11-character YouTube video id, or None if unrecognized."""
    match = _VIDEO_ID_PATTERN.search(url.strip())
    return match.group(1) if match else None
