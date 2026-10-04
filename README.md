# aqua-whisper

Async YouTube transcript API: submit a video URL and webhook; the worker fetches manual or auto subtitles (via yt-dlp) or falls back to Whisper, then POSTs the result to your webhook.
Optionally generate and save a summary through an OpenAI-compatible LLM.

## Features

- **POST /transcript** — Submit a YouTube URL and webhook URL; get a `task_id` immediately (202). No polling; the worker calls your webhook when done.
- **Pipeline** — Tries manual subtitles → original-language auto captions → Whisper transcription. Always returns plain text in the video's original language: the auto captions generated from the original audio (yt-dlp `-orig` tracks) are preferred over machine-translated tracks and over uploaded subtitles in another language. Manual subtitles are fetched for the languages in `SUBTITLE_LANGS` (default `zh.*,en`, first match wins); a failed subtitle download (e.g. YouTube HTTP 429 rate limiting) falls back to the next strategy instead of failing the job; only finished videos (yt-dlp `live_status` of `not_live` or `was_live`) are processed, videos ≤ 60s are rejected with a clear error, and generated transcripts are saved durably to a SQLite store with their title, channel, duration, and upload date (videos already in the store are skipped; set `TRANSCRIPT_DEDUP=false` to re-transcribe).
- **Summaries** — Set `summarize: true` to generate concise bullet points in the transcript's language using the official OpenAI Python SDK. Transcripts and summaries are saved to SQLite. The API defaults to transcript-only; the web UI requests and displays summaries.
- **Web UI** — Single-page frontend at `/` with `/ui/transcript` submission, polling, and saved-transcript history. No auth; deploy behind a reverse proxy (e.g. Cloudflare) for rate limiting and bot protection.
- **Docker** — One image for both the FastAPI app and the Celery worker. Redis is external.

## Requirements

- **Redis** — Existing instance; not included in Compose. Set `REDIS_URL` (e.g. `redis://host.docker.internal:6379/0` for local Docker).
- **SQLite** — Durable transcript storage; ships with Python, no extra service. A single file at `TRANSCRIPT_DB_PATH` (default `./data/transcripts.db`).
- **LLM** — For summaries, configure an OpenAI-compatible chat completions service with `LLM_BASE_URL`, `LLM_API_KEY`, and `LLM_MODEL`. Transcript-only operation does not require these settings.
- **Python 3.13** — For local development.

## Quick start

### Local development

```bash
# Install deps (uv)
uv sync --all-extras

# Set env
export REDIS_URL=redis://localhost:6379/0

# For summaries (or set these in .env):
export LLM_BASE_URL=https://api.openai.com/v1
export LLM_API_KEY=your-llm-api-key
export LLM_MODEL=your-model-name

# Run API
uv run uvicorn app.main:app --reload --port 8000

# In another terminal: run worker
# On macOS: use --pool=solo to avoid SIGABRT when tasks load faster-whisper (prefork + ObjC fork-safety). Linux/Docker can use the default prefork.
uv run celery -A app.celery_app worker --loglevel=info --concurrency=1 --pool=solo
```

### Docker (API + worker)

```bash
# Configure: copy the example env file and edit it (set REDIS_URL;
# for local Docker use redis://host.docker.internal:6379/0)
cp .env.example .env

# One-time: create the external network the stack attaches to
docker network create aqua-whisper-backend

# Build and run (builds the image locally as aqua-whisper:latest)
docker compose up --build
```

- **API:** http://localhost:8000  
- **Health:** `GET /health` → `{"status":"ok"}`  
- **Docs:** http://localhost:8000/docs  
- **Transcripts:** saved durably to SQLite at `./data/transcripts.db` (bind-mounted at `/data`); override the host dir with `AQUA_WHISPER_DATA_DIR`.  

With no extra configuration the Compose file builds the image locally and publishes the API on port 8000. A few `AQUA_WHISPER_*` variables (documented in `.env.example`) switch it to a server-style deployment: pull a prebuilt image, change the host port, attach to an existing external network, and bind a local Whisper model directory.

## Production deployment

Pushes to `main` are built and deployed automatically by CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)):

1. **Check** — every push and PR runs the Python Ruff checks, the mypy type check, the web ESLint check, and the pytest suite.
2. **Build** — when checks pass, the image is pushed to `ghcr.io/wkf2000/aqua-whisper` (tagged `latest` plus the commit sha).
3. **Deploy** — CI SSHes into the server and, in the deploy directory, runs `docker compose -f docker-compose.yml pull`, then `up -d` (Compose recreates only the services whose image or config changed, with no full downtime).

The server keeps its **own copy** of the Compose file (named `docker-compose.yml`) and a `.env`; it is not a git clone of this repo. The server's `.env` holds the production values for the same variables the local defaults stand in for:

```dotenv
AQUA_WHISPER_IMAGE=ghcr.io/wkf2000/aqua-whisper:latest
AQUA_WHISPER_PORT=8509
AQUA_WHISPER_NETWORK=1panel-network
AQUA_WHISPER_MODEL_DIR=/home/michael/aqua-whisper/whisper-model/faster-whisper-base
AQUA_WHISPER_DATA_DIR=/home/michael/aqua-whisper/data
```

After changing `docker-compose.yaml` in this repo, copy it to the server as `docker-compose.yml` and add any new variables to the server's `.env` before the next deploy — otherwise `docker compose pull` tries to pull the default local image name (`aqua-whisper:latest`) from Docker Hub and fails. The transcript store is bind-mounted from `AQUA_WHISPER_DATA_DIR` (default `./data` next to the Compose file); back it up by copying that directory.

## API summary

| Endpoint           | Auth | Description |
|--------------------|------|-------------|
| `GET /health`      | No   | 200 when API is up |
| `POST /transcript` | No   | Body: `video_url`, `webhook_url` (YouTube only), optional `author`, and optional `summarize` (default `false`). Returns 202 + `task_id`. |

**Webhook (worker → you):** One POST when the job finishes. Payload: `task_id`, `author`, `status` (`"success"` \| `"failed"`), and on success `source` (`"manual"` \| `"auto"` \| `"whisper"`), `transcript` (plain text), and `summary` (plain text or null); on transcription failure `error`.

Example request body:

```json
{
  "video_url": "https://www.youtube.com/watch?v=abc123def45",
  "webhook_url": "https://example.com/webhook",
  "summarize": true
}
```

### Summary behavior

- `summarize` defaults to `false`. When omitted or false, no LLM calls are made. A saved summary is still returned if available; otherwise `summary` is null.
- With `summarize: true` and deduplication enabled, a saved summary is reused. If missing, the stored transcript is summarized without fetching the video again.
- Summaries are concise bullet points in the transcript's language, generated from the full transcript in a single non-streaming chat completion request. The provider must support the transcript's length; context-limit errors are handled like other LLM failures.
- Missing LLM configuration, provider errors, timeouts, or invalid/empty output save and return the literal summary `"error"`. The job still reports `"success"` with its transcript. Saved `"error"` summaries are reused rather than retried.
- Existing databases gain a nullable summary column without backfilling or changing existing values. Old videos remain untouched until submitted with `summarize: true`; then only their missing summary is saved, preserving transcript, metadata, and timestamps.
- `TRANSCRIPT_DEDUP=false` retains explicit re-transcription: requesting a summary also regenerates it. Transcript-only re-transcription preserves any saved summary.

## Web UI

The repository also ships a small frontend (`static/index.html` for generating summaries, `static/history.html` for browsing saved summaries and video metadata) served by the API. It always submits `summarize: true`, shows the summary instead of transcript text, and copies the summary. History includes a Summary preview column with expandable full summaries. Rows without summaries show `No summary available`; failed summaries show `error`.

| Endpoint                | Auth | Description |
|-------------------------|------|-------------|
| `GET /`                 | No   | Summary frontend. |
| `GET /history`          | No   | History page: saved summaries with search, source/sort filters, and expandable rows. |
| `POST /ui/transcript`   | No   | Body: `video_url` (YouTube only), optional `summarize` (default `false`; the frontend sends `true`). Returns 202 + `task_id`. |
| `GET /ui/transcript/{task_id}` | No | Polls the stored result: `pending`, `success` with `source`, `transcript`, and `summary`, or `failed` with `error`. |
| `GET /ui/history`       | No   | Lists saved transcripts with metadata and summary, but no transcript text. Query params: `q` (search title/channel/video id), `source` (`manual` \| `auto` \| `whisper`), `sort` (`newest` \| `oldest` \| `longest` \| `shortest` \| `title`), `limit` (1&ndash;200), `offset`. Returns `{items, total, limit, offset}`. |
| `GET /ui/history/{video_id}` | No | One saved transcript with its metadata, full transcript, and summary. |

These endpoints carry no auth by design. In production the frontend is served behind **Cloudflare**, which provides rate limiting and bot protection; the API (`/transcript`) is intentionally also unauthenticated so it can be called directly.

## Environment

| Variable     | Required | Description |
|-------------|----------|-------------|
| `REDIS_URL` | Yes      | Redis broker URL for Celery (e.g. `redis://localhost:6379/0`). |
| `WHISPER_MODEL` | No   | Whisper model: size name (`base`, `small`, ...) or path to a local model dir. Default `base`. |
| `WHISPER_COMPUTE_TYPE` | No | CTranslate2 compute type: `int8`, `float16`, `float32`, or `auto`. Default `auto`. |
| `SUBTITLE_LANGS` | No   | Manual subtitle language regex(es) for yt-dlp `--sub-langs` (comma-separated; order is preference, first match wins; `all` for any language). Auto captions are always fetched in the video's original language first. Default `zh.*,en`. |
| `WHISPER_VAD_FILTER` | No | Skip non-speech segments in Whisper to reduce hallucinations. Default `true`. |
| `WHISPER_BATCHED`  | No   | Use faster-whisper batched inference (faster on CPU, higher peak memory). Default `false`. |
| `TRANSCRIPT_DEDUP` | No | Skip the pipeline when the video already has a saved transcript, whatever its age. Default `true`; `false` always re-runs and refreshes the stored row. |
| `TRANSCRIPT_DB_PATH` | No | SQLite file for durable transcript storage. Default `./data/transcripts.db`; in Docker fixed to `/data/transcripts.db` via the `AQUA_WHISPER_DATA_DIR` bind mount. |
| `LLM_BASE_URL` | For summaries | OpenAI-compatible API base URL including its API prefix, e.g. `https://api.openai.com/v1`. No default. |
| `LLM_API_KEY` | For summaries | Bearer API key for the LLM service. No default. |
| `LLM_MODEL` | For summaries | Model name accepted by the configured LLM service. No default. |
| `LLM_TIMEOUT_SECONDS` | No | Positive LLM request timeout in seconds. Default `120`; SDK retries are disabled. |
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
uv run mypy
npm ci && npm run lint
uv run pytest -v
```

## Design

See [docs/plans/2025-02-19-aqua-whisper-design.md](docs/plans/2025-02-19-aqua-whisper-design.md) for architecture and decisions.
