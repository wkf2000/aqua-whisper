"""Set required env vars before any app module is imported."""

import os
import tempfile

os.environ.setdefault("API_KEY", "test-secret-key")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
# Keep the SQLite transcript store out of the repo during tests.
os.environ.setdefault(
    "TRANSCRIPT_DB_PATH",
    os.path.join(tempfile.gettempdir(), "aqua-whisper-test-transcripts.db"),
)
