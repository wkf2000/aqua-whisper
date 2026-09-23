# aqua-whisper: single image for API and Celery worker.
#
# API (default):  docker run -p 8000:8000 <image>
# Worker:         docker run <image> celery -A app.celery_app worker --loglevel=info --concurrency=1
#
# Image includes: FastAPI app, Celery worker code, ffmpeg, deno (JS runtime
# for yt-dlp), and locked Python deps (yt-dlp, faster-whisper, etc.)
# installed from uv.lock via uv.

FROM python:3.13-slim

# uv: installs project dependencies from uv.lock (reproducible builds)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# deno: JS runtime yt-dlp needs to run YouTube's JS challenges (EJS).
# https://github.com/yt-dlp/yt-dlp/wiki/EJS
COPY --from=denoland/deno:bin-2.9.7 /deno /usr/local/bin/deno

# System deps: ffmpeg for yt-dlp and audio handling
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first (layer cached as long as uv.lock is unchanged).
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy the application and install the project itself.
COPY app ./app
COPY static ./static
RUN uv sync --frozen --no-dev

# Expose the venv binaries (uvicorn, celery, yt-dlp) on PATH.
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

# Default: run the API. Override with the celery worker command to run the worker.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
