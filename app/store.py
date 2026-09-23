"""Redis-backed storage for UI task results and transcript caching."""

import json

import redis

from app.config import settings

_redis = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)

_KEY_PREFIX = "ui:task:"
_DEFAULT_TTL = 3600

_TRANSCRIPT_PREFIX = "tr:cache:"


def save_task_result(task_id: str, payload: dict, ttl: int = _DEFAULT_TTL) -> None:
    """Store a task result in Redis with a TTL (default 1 hour)."""
    _redis.set(f"{_KEY_PREFIX}{task_id}", json.dumps(payload), ex=ttl)


def get_task_result(task_id: str) -> dict | None:
    """Retrieve a task result from Redis, or None if not found / expired."""
    raw = _redis.get(f"{_KEY_PREFIX}{task_id}")
    if raw is None:
        return None
    return json.loads(raw)


def get_cached_transcript(video_id: str) -> tuple[str, str] | None:
    """Return cached (source, transcript) for a video id, or None if not cached."""
    raw = _redis.get(f"{_TRANSCRIPT_PREFIX}{video_id}")
    if raw is None:
        return None
    data = json.loads(raw)
    return data["source"], data["transcript"]


def cache_transcript(video_id: str, source: str, transcript: str) -> None:
    """Cache (source, transcript) for a video id with the configured TTL."""
    _redis.set(
        f"{_TRANSCRIPT_PREFIX}{video_id}",
        json.dumps({"source": source, "transcript": transcript}),
        ex=settings.TRANSCRIPT_CACHE_TTL,
    )
