"""Redis-backed storage for UI task results."""

import json

import redis

from app.config import settings

_redis = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)

_KEY_PREFIX = "ui:task:"
_DEFAULT_TTL = 3600


def save_task_result(task_id: str, payload: dict, ttl: int = _DEFAULT_TTL) -> None:
    """Store a task result in Redis with a TTL (default 1 hour)."""
    _redis.set(f"{_KEY_PREFIX}{task_id}", json.dumps(payload), ex=ttl)


def get_task_result(task_id: str) -> dict | None:
    """Retrieve a task result from Redis, or None if not found / expired."""
    raw = _redis.get(f"{_KEY_PREFIX}{task_id}")
    if raw is None:
        return None
    return json.loads(raw)
