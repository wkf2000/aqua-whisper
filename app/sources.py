"""URL validation for the video sources the download pipeline supports."""

import re

from app.youtube import is_youtube_url

# x.com and twitter.com (with optional www. / mobile.); both serve the same posts.
_X_HOST_PATTERN = re.compile(
    r"^https?://(www\.|mobile\.)?(x\.com|twitter\.com)/",
    re.IGNORECASE,
)


def is_x_url(url: str) -> bool:
    """Return True if url is an X (x.com or twitter.com) URL, else False."""
    if not url or not url.strip():
        return False
    return bool(_X_HOST_PATTERN.match(url.strip()))


def is_downloadable_url(url: str) -> bool:
    """Return True if the download pipeline supports url (YouTube or X), else False."""
    return is_youtube_url(url) or is_x_url(url)
