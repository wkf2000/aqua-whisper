"""Tests for the history UI API: list filters, pagination, and detail."""

import os
from pathlib import Path

from fastapi.testclient import TestClient

# Set env before importing app so pydantic-settings picks them up.
os.environ.setdefault("API_KEY", "test-secret-key")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app import db
from app.config import settings
from app.main import app

client = TestClient(app)


def _use_db(monkeypatch, tmp_path) -> Path:
    """Point the store at a fresh per-test database file."""
    path = tmp_path / "data" / "transcripts.db"
    monkeypatch.setattr(settings, "TRANSCRIPT_DB_PATH", str(path))
    return path


def test_history_empty_store_returns_no_items(monkeypatch, tmp_path) -> None:
    """An empty store lists zero items."""
    _use_db(monkeypatch, tmp_path)
    res = client.get("/ui/history")
    assert res.status_code == 200
    assert res.json() == {"items": [], "total": 0, "limit": 50, "offset": 0}


def test_history_lists_saved_transcripts(monkeypatch, tmp_path) -> None:
    """Saved rows are listed with metadata and without the transcript text."""
    _use_db(monkeypatch, tmp_path)
    db.save_transcript("vid11111111", "manual", "some text", title="Alpha", channel="Chan")

    res = client.get("/ui/history")

    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    item = data["items"][0]
    assert item["video_id"] == "vid11111111"
    assert item["title"] == "Alpha"
    assert item["channel"] == "Chan"
    assert item["source"] == "manual"
    assert "transcript" not in item


def test_history_search_and_source_filters(monkeypatch, tmp_path) -> None:
    """q matches titles; source narrows; filters combine."""
    _use_db(monkeypatch, tmp_path)
    db.save_transcript("vid11111111", "manual", "a", title="Alpha Talk")
    db.save_transcript("vid22222222", "whisper", "b", title="Beta Talk")

    res = client.get("/ui/history", params={"q": "beta"})
    data = res.json()
    assert data["total"] == 1
    assert data["items"][0]["video_id"] == "vid22222222"

    res = client.get("/ui/history", params={"source": "whisper"})
    assert res.json()["total"] == 1

    res = client.get("/ui/history", params={"q": "alpha", "source": "whisper"})
    assert res.json()["total"] == 0


def test_history_pagination_params(monkeypatch, tmp_path) -> None:
    """limit/offset page through results while total stays the full count."""
    _use_db(monkeypatch, tmp_path)
    for i in range(3):
        db.save_transcript(f"vid0000000{i}", "manual", f"t{i}")

    res = client.get("/ui/history", params={"limit": 2, "offset": 2})
    data = res.json()
    assert data["total"] == 3
    assert len(data["items"]) == 1
    assert data["limit"] == 2
    assert data["offset"] == 2


def test_history_rejects_invalid_params(monkeypatch, tmp_path) -> None:
    """Unknown sources/sorts and out-of-range limits are rejected with 400."""
    _use_db(monkeypatch, tmp_path)
    assert client.get("/ui/history", params={"source": "nope"}).status_code == 400
    assert client.get("/ui/history", params={"sort": "weird"}).status_code == 400
    assert client.get("/ui/history", params={"limit": 0}).status_code == 400
    assert client.get("/ui/history", params={"offset": -1}).status_code == 400


def test_history_rejects_huge_offset(monkeypatch, tmp_path) -> None:
    """Offsets beyond the allowed bound are rejected with 400, not a 500."""
    _use_db(monkeypatch, tmp_path)
    assert client.get("/ui/history", params={"offset": 2**63}).status_code == 400
    assert client.get("/ui/history", params={"offset": 10**9}).status_code == 200


def test_history_detail_returns_transcript(monkeypatch, tmp_path) -> None:
    """The detail endpoint returns the full stored transcript with metadata."""
    _use_db(monkeypatch, tmp_path)
    db.save_transcript("vid11111111", "manual", "the text", title="Alpha")

    res = client.get("/ui/history/vid11111111")

    assert res.status_code == 200
    data = res.json()
    assert data["transcript"] == "the text"
    assert data["title"] == "Alpha"


def test_history_detail_unknown_video_404s(monkeypatch, tmp_path) -> None:
    """An unknown video id returns 404."""
    _use_db(monkeypatch, tmp_path)
    assert client.get("/ui/history/missing00000").status_code == 404


def test_history_page_is_served() -> None:
    """GET /history serves the history page HTML."""
    res = client.get("/history")
    assert res.status_code == 200
    assert "History" in res.text
