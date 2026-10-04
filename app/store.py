"""Redis-backed storage for UI task results."""

import json
from typing import Any, cast

import redis

from app.config import settings

_redis = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)

_KEY_PREFIX = "ui:task:"
_DEFAULT_TTL = 3600


def save_task_result(task_id: str, payload: dict[str, Any], ttl: int = _DEFAULT_TTL) -> None:
    """Store a task result in Redis with a TTL (default 1 hour)."""
    _redis.set(f"{_KEY_PREFIX}{task_id}", json.dumps(payload), ex=ttl)


def save_task_progress(task_id: str, stage: str, ttl: int = _DEFAULT_TTL) -> None:
    """Store a stage update for a still-running UI task.

    The payload keeps the "pending" status, so old frontends keep polling, and
    the final save_task_result for the same task overwrites this row.
    """
    save_task_result(task_id, {"status": "pending", "stage": stage}, ttl=ttl)


def get_task_result(task_id: str) -> dict[str, Any] | None:
    """Retrieve a task result from Redis, or None if not found / expired."""
    # redis-py annotates get() with a sync/async union; decode_responses=True makes it str.
    raw = cast("str | None", _redis.get(f"{_KEY_PREFIX}{task_id}"))
    if raw is None:
        return None
    parsed: dict[str, Any] = json.loads(raw)
    return parsed
