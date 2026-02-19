# aqua-whisper

Async YouTube transcript API: submit a video URL and webhook; the worker fetches manual or auto subtitles (via yt-dlp) or falls back to Whisper, then POSTs the result to your webhook.

## Features

- **POST /transcript** — Submit a YouTube URL and webhook URL; get a `task_id` immediately (202). No polling; the worker calls your webhook when done.
- **Pipeline** — Tries manual subtitles → auto-generated subtitles → Whisper transcription. Always returns VTT.
- **Single API key** — Env-based auth; use `Authorization: Bearer <key>` or `X-API-Key: <key>`.
- **Docker** — One image for both the FastAPI app and the Celery worker. Redis is external.

## Requirements

- **Redis** — Existing instance; not included in Compose. Set `REDIS_URL` (e.g. `redis://host.docker.internal:6379/0` for local Docker).
- **Python 3.13** — For local development.

## Quick start

### Local development

```bash
# Install deps (uv)
uv sync --all-extras

# Set env
export API_KEY=your-secret-key
export REDIS_URL=redis://localhost:6379/0

# Run API
uv run uvicorn app.main:app --reload --port 8000

# In another terminal: run worker
uv run celery -A app.celery_app worker --loglevel=info --concurrency=1
```

### Docker (API + worker)

```bash
# Set Redis and API key (e.g. in .env)
export REDIS_URL=redis://host.docker.internal:6379/0
export API_KEY=your-secret-key

# Build and run
docker compose up --build
```

- **API:** http://localhost:8000  
- **Health:** `GET /health` → `{"status":"ok"}`  
- **Docs:** http://localhost:8000/docs  

## API summary

| Endpoint           | Auth | Description |
|--------------------|------|-------------|
| `GET /health`      | No   | 200 when API is up |
| `POST /transcript` | Yes  | Body: `video_url`, `webhook_url` (YouTube only). Returns 202 + `task_id`. |

**Webhook (worker → you):** One POST when the job finishes. Payload: `task_id`, `status` (`"success"` \| `"failed"`), and on success `source` (`"manual"` \| `"auto"` \| `"whisper"`) and `transcript` (VTT string); on failure `error`.

## Environment

| Variable     | Required | Description |
|-------------|----------|-------------|
| `API_KEY`   | Yes (API) | Shared secret for `POST /transcript` and `/protected`. |
| `REDIS_URL` | Yes      | Redis broker URL for Celery (e.g. `redis://localhost:6379/0`). |

## Tests and lint

```bash
uv run ruff check . && uv run ruff format --check .
uv run pytest -v
```

## Design

See [docs/plans/2025-02-19-aqua-whisper-design.md](docs/plans/2025-02-19-aqua-whisper-design.md) for architecture and decisions.
