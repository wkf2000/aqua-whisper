"""Tests for the SQLite transcript store."""

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import db
from app.config import settings

_VIDEO_ID = "abc123def45"

# The schema before video metadata columns existed (the first released version).
_V1_SCHEMA = """
CREATE TABLE transcripts (
    video_id   TEXT PRIMARY KEY,
    source     TEXT NOT NULL,
    transcript TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""


def _use_db(monkeypatch, tmp_path) -> Path:
    """Point the store at a fresh per-test database file (in a missing dir)."""
    path = tmp_path / "data" / "transcripts.db"
    monkeypatch.setattr(settings, "TRANSCRIPT_DB_PATH", str(path))
    return path


def test_save_and_get_roundtrip(monkeypatch, tmp_path) -> None:
    """A saved transcript is returned by get_stored_transcript with its metadata."""
    _use_db(monkeypatch, tmp_path)
    db.save_transcript(
        _VIDEO_ID,
        "manual",
        "some text",
        title="A Talk",
        channel="Some Channel",
        duration=300.0,
        upload_date="2026-01-01",
    )

    row = db.get_stored_transcript(_VIDEO_ID)

    assert row is not None
    assert row.video_id == _VIDEO_ID
    assert row.source == "manual"
    assert row.transcript == "some text"
    assert row.title == "A Talk"
    assert row.channel == "Some Channel"
    assert row.duration == 300.0
    assert row.upload_date == "2026-01-01"
    updated = datetime.strptime(row.updated_at, db._TIMESTAMP_FORMAT).replace(tzinfo=timezone.utc)
    assert datetime.now(timezone.utc) - updated < timedelta(minutes=1)


def test_get_unknown_video_returns_none(monkeypatch, tmp_path) -> None:
    """Nothing is stored for an unknown video id."""
    _use_db(monkeypatch, tmp_path)
    assert db.get_stored_transcript("missing00000") is None


def test_save_upsert_refreshes_existing_row(monkeypatch, tmp_path) -> None:
    """Re-saving a video id refreshes its row instead of creating a second one."""
    _use_db(monkeypatch, tmp_path)
    db.save_transcript(_VIDEO_ID, "manual", "first", title="First Title")
    db.save_transcript(_VIDEO_ID, "whisper", "second", title="Second Title", channel="C")

    row = db.get_stored_transcript(_VIDEO_ID)

    assert row is not None
    assert row.source == "whisper"
    assert row.transcript == "second"
    assert row.title == "Second Title"
    assert row.channel == "C"


def test_creates_parent_directories(monkeypatch, tmp_path) -> None:
    """The store creates missing parent directories for the database file."""
    path = _use_db(monkeypatch, tmp_path)

    db.save_transcript(_VIDEO_ID, "manual", "text")

    assert path.exists()


def test_migrates_v1_database_by_adding_metadata_columns(monkeypatch, tmp_path) -> None:
    """A database created before metadata columns existed is upgraded on connect."""
    path = _use_db(monkeypatch, tmp_path)
    path.parent.mkdir(parents=True)
    conn = sqlite3.connect(path)
    conn.executescript(_V1_SCHEMA)
    conn.execute(
        "INSERT INTO transcripts (video_id, source, transcript) "
        "VALUES ('old12345678', 'manual', 'old text')"
    )
    conn.commit()
    conn.close()

    db.save_transcript(_VIDEO_ID, "auto", "new text", title="T", channel="C", duration=61.0)

    new_row = db.get_stored_transcript(_VIDEO_ID)
    assert new_row is not None
    assert new_row.title == "T"
    assert new_row.channel == "C"
    assert new_row.duration == 61.0
    assert new_row.upload_date is None

    # The pre-migration row survives with NULL metadata.
    old_row = db.get_stored_transcript("old12345678")
    assert old_row is not None
    assert old_row.transcript == "old text"
    assert old_row.title is None
    assert old_row.duration is None
