"""Set required env vars before any app module is imported."""

import os

os.environ.setdefault("API_KEY", "test-secret-key")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
