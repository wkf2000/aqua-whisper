# aqua-whisper: single image for API and Celery worker.
#
# API (default):  docker run -p 8000:8000 <image>
# Worker:         docker run <image> celery -A app.celery_app worker --loglevel=info --concurrency=1
#
# Image includes: FastAPI app, Celery worker code, yt-dlp, FFmpeg, faster-whisper (Python deps from pyproject.toml).

FROM python:3.13-slim

# System deps: ffmpeg for yt-dlp and audio handling
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# yt-dlp for YouTube download
RUN pip install --no-cache-dir yt-dlp

WORKDIR /app

# Copy project and install Python deps (includes faster-whisper, FastAPI, Celery, etc.)
COPY pyproject.toml ./
COPY README.md ./
COPY app ./app

RUN pip install --no-cache-dir .

EXPOSE 8000

# Default: run the API. Override with celery worker command to run the worker.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
