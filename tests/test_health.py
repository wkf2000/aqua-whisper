"""Tests for GET /health."""

import os

from fastapi.testclient import TestClient

# Set env before importing app so pydantic-settings picks them up.
os.environ.setdefault("API_KEY", "test-secret-key")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.main import app

client = TestClient(app)


def test_health_returns_200() -> None:
    """GET /health returns 200 with status ok."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
