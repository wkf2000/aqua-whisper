"""Tests for the SQLite transcript store."""

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import db
from app.config import settings

_VIDEO_ID = "abc123def45"


def _use_db(monkeypatch, tmp_path) -> Path:
    """Point the store at a fresh per-test database file (in a missing dir)."""
    path = tmp_path / "data" / "transcripts.db"
    monkeypatch.setattr(settings, "TRANSCRIPT_DB_PATH", str(path))
    return path


def test_save_and_get_roundtrip(monkeypatch, tmp_path) -> None:
    """A saved transcript is returned by get_stored_transcript with its updated_at."""
    _use_db(monkeypatch, tmp_path)
    db.save_transcript(_VIDEO_ID, "manual", "some text")

    row = db.get_stored_transcript(_VIDEO_ID)

    assert row is not None
    source, transcript, updated_at = row
    assert source == "manual"
    assert transcript == "some text"
    updated = datetime.strptime(updated_at, db._TIMESTAMP_FORMAT).replace(tzinfo=timezone.utc)
    assert datetime.now(timezone.utc) - updated < timedelta(minutes=1)


def test_get_unknown_video_returns_none(monkeypatch, tmp_path) -> None:
    """Nothing is stored for an unknown video id."""
    _use_db(monkeypatch, tmp_path)
    assert db.get_stored_transcript("missing00000") is None


def test_save_upsert_refreshes_existing_row(monkeypatch, tmp_path) -> None:
    """Re-saving a video id refreshes its row instead of creating a second one."""
    _use_db(monkeypatch, tmp_path)
    db.save_transcript(_VIDEO_ID, "manual", "first")
    db.save_transcript(_VIDEO_ID, "whisper", "second")

    row = db.get_stored_transcript(_VIDEO_ID)

    assert row is not None
    assert row[0] == "whisper"
    assert row[1] == "second"


def test_creates_parent_directories(monkeypatch, tmp_path) -> None:
    """The store creates missing parent directories for the database file."""
    path = _use_db(monkeypatch, tmp_path)

    db.save_transcript(_VIDEO_ID, "manual", "text")

    assert path.exists()


def test_get_fresh_transcript_respects_max_age(monkeypatch, tmp_path) -> None:
    """Fresh rows are returned; stale rows and unknown ids are misses."""
    _use_db(monkeypatch, tmp_path)
    db.save_transcript(_VIDEO_ID, "manual", "some text")

    assert db.get_fresh_transcript(_VIDEO_ID, 3600) == ("manual", "some text")
    assert db.get_fresh_transcript(_VIDEO_ID, 0) is None
    assert db.get_fresh_transcript("missing00000", 3600) is None


def test_get_fresh_transcript_returns_none_when_stale(monkeypatch, tmp_path) -> None:
    """A row older than max_age_seconds is a miss; a wider window accepts it."""
    _use_db(monkeypatch, tmp_path)
    db.save_transcript(_VIDEO_ID, "manual", "some text")
    conn = sqlite3.connect(settings.TRANSCRIPT_DB_PATH)
    conn.execute(
        "UPDATE transcripts SET updated_at = datetime('now', '-2 hours') WHERE video_id = ?",
        (_VIDEO_ID,),
    )
    conn.commit()
    conn.close()

    assert db.get_fresh_transcript(_VIDEO_ID, 3600) is None
    assert db.get_fresh_transcript(_VIDEO_ID, 7201) == ("manual", "some text")
