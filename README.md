# aqua-whisper

Async YouTube transcript API: submit a video URL and webhook; the worker fetches manual or auto subtitles (via yt-dlp) or falls back to Whisper, then POSTs the result to your webhook.

## Features

- **POST /transcript** — Submit a YouTube URL and webhook URL; get a `task_id` immediately (202). No polling; the worker calls your webhook when done.
- **Pipeline** — Tries manual subtitles → auto-generated subtitles → Whisper transcription. Always returns plain text.
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
# On macOS: use --pool=solo to avoid SIGABRT when tasks load faster-whisper (prefork + ObjC fork-safety). Linux/Docker can use the default prefork.
uv run celery -A app.celery_app worker --loglevel=info --concurrency=1 --pool=solo
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

**Webhook (worker → you):** One POST when the job finishes. Payload: `task_id`, `status` (`"success"` \| `"failed"`), and on success `source` (`"manual"` \| `"auto"` \| `"whisper"`) and `transcript` (plain text); on failure `error`.

## Environment

| Variable     | Required | Description |
|-------------|----------|-------------|
| `API_KEY`   | Yes (API) | Shared secret for `POST /transcript` and `/protected`. |
| `REDIS_URL` | Yes      | Redis broker URL for Celery (e.g. `redis://localhost:6379/0`). |
| `ENV`       | No       | Environment label for logs/traces (e.g. `dev`, `prod`). |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | No | OTLP HTTP endpoint for traces (e.g. `http://openobserve:5080/api/default/v1/traces`). If unset, spans are not exported. |
| `OTEL_EXPORTER_OTLP_HEADERS`  | No | Optional headers: comma-separated `key=value` (e.g. `Authorization=Basic <base64>,stream-name=default` for OpenObserve). |

## Logging and tracing

### Logs

- **Library:** [structlog](https://www.structlog.org/) — all app logs are JSON, one object per line, written to **stdout**.
- **Fields:** `level`, `timestamp` (ISO/RFC3339), `service` (`aqua-whisper-api` or `aqua-whisper-worker`), optional `environment`, and when a span is active, `trace_id` and `span_id` for correlation.
- **Flow:** In Docker, container stdout is collected by [Vector](https://vector.dev/) (`docker_logs` source with `codec: json`), then forwarded to OpenObserve (or another sink). No extra app config is needed for log shipping — just ensure the app logs to stdout.

### Traces

- **Library:** [OpenTelemetry](https://opentelemetry.io/) — the app and worker create spans (e.g. HTTP requests, `run_transcript_pipeline` task).
- **Export:** If `OTEL_EXPORTER_OTLP_ENDPOINT` is set, spans are sent via OTLP HTTP to that URL (e.g. OpenObserve at `http://<host>:5080/api/default/v1/traces`). Optional `OTEL_EXPORTER_OTLP_HEADERS` can set `Authorization: Basic ...` and `stream-name: default` to match OpenObserve’s ingest API. If endpoint is unset, no exporter is registered and tests/local runs do not try to connect to a collector.
- **Correlation:** Logs automatically include `trace_id` and `span_id` when there is an active span, so you can link log lines to traces in OpenObserve.

## Tests and lint

```bash
uv run ruff check . && uv run ruff format --check .
uv run pytest -v
```

## Design

See [docs/plans/2025-02-19-aqua-whisper-design.md](docs/plans/2025-02-19-aqua-whisper-design.md) for architecture and decisions.
