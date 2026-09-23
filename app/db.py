"""SQLite-backed durable storage for generated transcripts.

Every completed transcript is stored by video id and kept forever, along with
the video metadata available at transcription time (title, channel, duration,
upload date). While TRANSCRIPT_DEDUP is enabled, a stored video is never
re-transcribed (see app.tasks._transcript_with_dedup).
"""

import os
import sqlite3
from contextlib import closing
from typing import NamedTuple

from app.config import settings

# SQLite datetime('now') output, in UTC.
_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS transcripts (
    video_id   TEXT PRIMARY KEY,
    source     TEXT NOT NULL,
    transcript TEXT NOT NULL,
    title      TEXT,
    channel    TEXT,
    duration   REAL,
    upload_date TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

# Columns added after the first release; applied to databases that predate them.
_MIGRATIONS = (
    ("title", "ALTER TABLE transcripts ADD COLUMN title TEXT"),
    ("channel", "ALTER TABLE transcripts ADD COLUMN channel TEXT"),
    ("duration", "ALTER TABLE transcripts ADD COLUMN duration REAL"),
    ("upload_date", "ALTER TABLE transcripts ADD COLUMN upload_date TEXT"),
)


class StoredTranscript(NamedTuple):
    """A stored transcript row; video metadata is None for older rows."""

    video_id: str
    source: str
    transcript: str
    title: str | None
    channel: str | None
    duration: float | None
    upload_date: str | None
    created_at: str
    updated_at: str


def _connect() -> sqlite3.Connection:
    """Open a connection to the transcript store.

    WAL keeps readers and the writer from blocking each other, the schema
    statement self-initializes the database file, and _migrate upgrades
    databases created by older versions of the app.
    """
    path = settings.TRANSCRIPT_DB_PATH
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(_SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns missing from databases created by older versions."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(transcripts)")}
    for column, ddl in _MIGRATIONS:
        if column not in existing:
            conn.execute(ddl)


def save_transcript(
    video_id: str,
    source: str,
    transcript: str,
    *,
    title: str | None = None,
    channel: str | None = None,
    duration: float | None = None,
    upload_date: str | None = None,
) -> None:
    """Store the transcript and video metadata, refreshing the row if it exists."""
    with closing(_connect()) as conn, conn:
        conn.execute(
            """
            INSERT INTO transcripts
                (video_id, source, transcript, title, channel, duration, upload_date)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(video_id) DO UPDATE SET
                source = excluded.source,
                transcript = excluded.transcript,
                title = excluded.title,
                channel = excluded.channel,
                duration = excluded.duration,
                upload_date = excluded.upload_date,
                updated_at = datetime('now')
            """,
            (video_id, source, transcript, title, channel, duration, upload_date),
        )


def get_stored_transcript(video_id: str) -> StoredTranscript | None:
    """Return the stored row for a video id, or None if not stored."""
    with closing(_connect()) as conn:
        row = conn.execute(
            """
            SELECT video_id, source, transcript, title, channel, duration, upload_date,
                   created_at, updated_at
            FROM transcripts WHERE video_id = ?
            """,
            (video_id,),
        ).fetchone()
    if row is None:
        return None
    return StoredTranscript(*row)
