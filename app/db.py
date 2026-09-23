"""SQLite-backed durable storage for generated transcripts.

Every completed transcript is stored by video id and kept forever.
TRANSCRIPT_CACHE_TTL does not delete rows; it only limits how old a stored
transcript may be before the pipeline re-runs and refreshes it (see
app.tasks._transcript_with_cache).
"""

import os
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone

from app.config import settings

# SQLite datetime('now') output, in UTC.
_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS transcripts (
    video_id   TEXT PRIMARY KEY,
    source     TEXT NOT NULL,
    transcript TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""


def _connect() -> sqlite3.Connection:
    """Open a connection to the transcript store.

    WAL keeps readers and the writer from blocking each other, and the schema
    statement self-initializes the database file (a no-op once it exists).
    """
    path = settings.TRANSCRIPT_DB_PATH
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(_SCHEMA)
    return conn


def save_transcript(video_id: str, source: str, transcript: str) -> None:
    """Store the transcript for a video id, refreshing the row if it already exists."""
    with closing(_connect()) as conn, conn:
        conn.execute(
            """
            INSERT INTO transcripts (video_id, source, transcript)
            VALUES (?, ?, ?)
            ON CONFLICT(video_id) DO UPDATE SET
                source = excluded.source,
                transcript = excluded.transcript,
                updated_at = datetime('now')
            """,
            (video_id, source, transcript),
        )


def get_stored_transcript(video_id: str) -> tuple[str, str, str] | None:
    """Return (source, transcript, updated_at) for a video id, or None if not stored."""
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT source, transcript, updated_at FROM transcripts WHERE video_id = ?",
            (video_id,),
        ).fetchone()
    if row is None:
        return None
    return row[0], row[1], row[2]


def get_fresh_transcript(video_id: str, max_age_seconds: int) -> tuple[str, str] | None:
    """Return (source, transcript) only when stored and no older than max_age_seconds."""
    row = get_stored_transcript(video_id)
    if row is None:
        return None
    source, transcript, updated_at = row
    updated = datetime.strptime(updated_at, _TIMESTAMP_FORMAT).replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if now - updated >= timedelta(seconds=max_age_seconds):
        return None
    return source, transcript
