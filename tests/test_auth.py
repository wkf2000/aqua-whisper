"""Tests for API key auth dependency."""

import os

from fastapi.testclient import TestClient

# Set env before importing app so pydantic-settings picks them up.
os.environ.setdefault("API_KEY", "test-secret-key")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.main import app

client = TestClient(app)


def test_protected_without_key_returns_401() -> None:
    """Request without Authorization or X-API-Key returns 401."""
    response = client.get("/protected")
    assert response.status_code == 401


def test_protected_with_wrong_key_returns_401() -> None:
    """Request with wrong API key returns 401."""
    response = client.get(
        "/protected",
        headers={"Authorization": "Bearer wrong-key"},
    )
    assert response.status_code == 401

    response = client.get(
        "/protected",
        headers={"X-API-Key": "wrong-key"},
    )
    assert response.status_code == 401


def test_protected_with_correct_bearer_key_returns_200() -> None:
    """Request with correct Bearer key returns 200."""
    response = client.get(
        "/protected",
        headers={"Authorization": "Bearer test-secret-key"},
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_protected_with_correct_x_api_key_returns_200() -> None:
    """Request with correct X-API-Key returns 200."""
    response = client.get(
        "/protected",
        headers={"X-API-Key": "test-secret-key"},
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True}
