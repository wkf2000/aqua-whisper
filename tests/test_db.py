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


# Rows for listing tests: video_id, source, title, channel, duration, upload_date.
_SEED_ROWS = (
    ("vid11111111", "manual", "Alpha Talk", "Chan A", 300.0, "2026-01-01"),
    ("vid22222222", "auto", "Beta talk", "Chan B", 1200.0, "2026-02-01"),
    ("vid33333333", "whisper", "Gamma Show", "Chan A", 60.0, "2026-03-01"),
)


def _seed_listing(monkeypatch, tmp_path) -> None:
    """Seed three rows with distinct created_at values (vid3 newest, vid1 oldest)."""
    _use_db(monkeypatch, tmp_path)
    for video_id, source, title, channel, duration, upload_date in _SEED_ROWS:
        db.save_transcript(
            video_id,
            source,
            f"text {video_id}",
            title=title,
            channel=channel,
            duration=duration,
            upload_date=upload_date,
        )
    conn = sqlite3.connect(settings.TRANSCRIPT_DB_PATH)
    for video_id, days_ago in (("vid11111111", 3), ("vid22222222", 2), ("vid33333333", 1)):
        conn.execute(
            "UPDATE transcripts SET created_at = datetime('now', ?) WHERE video_id = ?",
            (f"-{days_ago} days", video_id),
        )
    conn.commit()
    conn.close()


def test_list_returns_all_newest_first_with_total(monkeypatch, tmp_path) -> None:
    """Default listing is newest first and reports the full total."""
    _seed_listing(monkeypatch, tmp_path)
    rows, total = db.list_transcripts()
    assert total == 3
    assert [r.video_id for r in rows] == ["vid33333333", "vid22222222", "vid11111111"]
    assert rows[0].title == "Gamma Show"
    assert rows[0].channel == "Chan A"
    assert rows[0].duration == 60.0
    assert rows[0].upload_date == "2026-03-01"


def test_list_search_matches_title_channel_and_video_id(monkeypatch, tmp_path) -> None:
    """q matches title (case-insensitive), channel, and video id."""
    _seed_listing(monkeypatch, tmp_path)
    rows, total = db.list_transcripts(q="beta")
    assert total == 1
    assert rows[0].video_id == "vid22222222"
    rows, total = db.list_transcripts(q="chan a")
    assert total == 2
    assert {r.video_id for r in rows} == {"vid11111111", "vid33333333"}
    rows, total = db.list_transcripts(q="vid3333")
    assert total == 1
    assert rows[0].video_id == "vid33333333"


def test_list_search_escapes_like_wildcards(monkeypatch, tmp_path) -> None:
    """Literal % and _ in the query do not act as LIKE wildcards."""
    _use_db(monkeypatch, tmp_path)
    db.save_transcript("vid44444444", "manual", "text", title="100% certain")
    db.save_transcript("vid55555555", "manual", "text", title="Beta talk")

    # "10%" unescaped would match "100% certain" via the trailing wildcard.
    assert db.list_transcripts(q="10%")[1] == 0
    assert db.list_transcripts(q="100%")[1] == 1
    # "Bet_" unescaped would match "Beta talk" via the underscore wildcard.
    assert db.list_transcripts(q="Bet_")[1] == 0
    assert db.list_transcripts(q="Beta")[1] == 1


def test_list_source_filter_combines_with_search(monkeypatch, tmp_path) -> None:
    """The source filter narrows the search results."""
    _seed_listing(monkeypatch, tmp_path)
    rows, total = db.list_transcripts(source="whisper")
    assert total == 1
    assert rows[0].video_id == "vid33333333"
    rows, total = db.list_transcripts(q="chan a", source="whisper")
    assert total == 1
    assert rows[0].video_id == "vid33333333"


def test_list_sort_orders(monkeypatch, tmp_path) -> None:
    """Whitelisted sorts order by age, duration, and title."""
    _seed_listing(monkeypatch, tmp_path)
    assert [r.video_id for r in db.list_transcripts(sort="oldest")[0]] == [
        "vid11111111",
        "vid22222222",
        "vid33333333",
    ]
    assert [r.video_id for r in db.list_transcripts(sort="longest")[0]] == [
        "vid22222222",
        "vid11111111",
        "vid33333333",
    ]
    assert [r.video_id for r in db.list_transcripts(sort="shortest")[0]] == [
        "vid33333333",
        "vid11111111",
        "vid22222222",
    ]
    assert [r.video_id for r in db.list_transcripts(sort="title")[0]] == [
        "vid11111111",
        "vid22222222",
        "vid33333333",
    ]


def test_list_sort_null_duration_last(monkeypatch, tmp_path) -> None:
    """Rows without duration (saved before metadata) sort last in duration sorts."""
    _seed_listing(monkeypatch, tmp_path)
    db.save_transcript("vid77777777", "manual", "no metadata")

    for sort in ("longest", "shortest"):
        rows, total = db.list_transcripts(sort=sort)
        assert total == 4
        assert rows[-1].video_id == "vid77777777"


def test_list_sort_null_title_last(monkeypatch, tmp_path) -> None:
    """Rows without a title (saved before metadata) sort last in the title sort."""
    _seed_listing(monkeypatch, tmp_path)
    db.save_transcript("vid77777777", "manual", "no metadata")

    rows, total = db.list_transcripts(sort="title")

    assert total == 4
    assert [r.video_id for r in rows[:3]] == ["vid11111111", "vid22222222", "vid33333333"]
    assert rows[-1].video_id == "vid77777777"


def test_list_pagination(monkeypatch, tmp_path) -> None:
    """limit/offset page through results while total stays the full count."""
    _seed_listing(monkeypatch, tmp_path)
    rows, total = db.list_transcripts(limit=2, offset=0)
    assert total == 3
    assert len(rows) == 2
    assert rows[0].video_id == "vid33333333"
    rows, total = db.list_transcripts(limit=2, offset=2)
    assert total == 3
    assert [r.video_id for r in rows] == ["vid11111111"]


def test_list_unknown_sort_falls_back_to_newest(monkeypatch, tmp_path) -> None:
    """Sort keys outside the whitelist fall back to newest; nothing is interpolated."""
    _seed_listing(monkeypatch, tmp_path)
    rows, total = db.list_transcripts(sort="newest; DROP TABLE transcripts")
    assert total == 3
    assert rows[0].video_id == "vid33333333"
    assert db.get_stored_transcript("vid11111111") is not None
