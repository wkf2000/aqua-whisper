# aqua-whisper Design

**Date:** 2025-02-19  
**Status:** Approved

## 1. Problem Statement

The service requires an asynchronous architecture to handle long-running video downloads and AI transcriptions. A synchronous API would cause timeouts and resource exhaustion on the Proxmox host.

## 2. Decisions Summary

| Topic | Decision |
|-------|----------|
| Auth | Single shared API key from env; validated per request |
| Webhook | One attempt only; no retries. Caller can resubmit if needed |
| Whisper confirmation | None; worker always runs full pipeline (subs → Whisper fallback) |
| Task status | Webhook-only delivery; no `GET /tasks/{id}` or result backend |
| Video source | YouTube only; validate URL format |
| Runner | Celery + Redis (broker only) |
| Python | 3.13 |
| Redis | Existing instance; not provisioned by this stack |

## 3. Architecture, Components, Deployment

- **FastAPI app:** Validates API key and YouTube URL, enqueues a Celery task with `video_url` and `webhook_url`, returns generated `task_id`. No result backend.
- **Celery worker:** Consumes tasks from Redis, runs transcript pipeline (yt-dlp → subs or Whisper), POSTs outcome to webhook once. Concurrency 1 or 2.
- **Redis:** Existing instance; used as Celery broker only. Connection via config (e.g. `REDIS_URL`).
- **Single Docker image:** One image contains FastAPI app, Celery worker code, yt-dlp, FFmpeg, and faster-whisper (or Whisper CLI). Two processes: API (e.g. uvicorn), worker (celery worker). Shared model volume optional.
- **Deployment:** Docker Compose with services `api` and `worker` (same image); Redis is external. Worker started with `--concurrency=1` or `2`.

## 4. API Contract

### POST /transcript

- **Request (JSON):** `video_url` (required, YouTube only), `webhook_url` (required).
- **Auth:** `Authorization: Bearer <API_KEY>` or `X-API-Key: <API_KEY>`; key from env. Invalid/missing → 401.
- **Response (202 Accepted):** `{ "task_id": "<uuid>" }`.
- **Errors:** 400 invalid/missing body or non-YouTube URL; 401 bad/missing API key; 503/500 if enqueue to Redis fails.

### Webhook POST (worker → caller)

- One POST per task when pipeline finishes (success or failure). No retries on webhook failure.
- **Payload (JSON):** `task_id`, `status` (`"success"` \| `"failed"`). On success: `source` (`"manual"` \| `"auto"` \| `"whisper"`), `transcript` (VTT string). On failure: `error` (short message).
- **Health:** GET /health (or /) returns 200 when API is up; optional Redis check.

## 5. Worker Pipeline

1. **Manual subs:** `yt-dlp --write-sub --skip-download --output "OUTPUT_NAME" "YOUTUBE_URL"`. If .vtt produced → use it, `source: "manual"`, done.
2. **Auto subs:** Else `yt-dlp --write-auto-sub --skip-download ...`. If .vtt produced → use it, `source: "auto"`, done.
3. **Whisper:** Else download audio (`yt-dlp -x --audio-format mp3 ...`), transcribe with Whisper (model **base**, output VTT), `source: "whisper"`. Use faster-whisper or `whisper` CLI; output format VTT.
4. **Cleanup:** After building transcript (any source), delete all temp files for this task (try/finally). On any failure, still call webhook with `status: "failed"` and `error`.

## 6. Error Handling, Config, Testing

- **API:** 400/401 as above; 503/500 on Redis enqueue failure.
- **Worker:** Catch pipeline exceptions; always POST webhook with status and error when failed; cleanup in try/finally. Webhook POST failure → log and drop (no retries). Optional Celery retries only for broker issues.
- **Config (env):** `API_KEY`, `REDIS_URL`; worker: same Redis, optional `CELERY_CONCURRENCY`, temp path; optional `WHISPER_MODEL` (default `base`).
- **Testing:** Unit tests for YouTube URL validation, request validation, 400/401, mocked Celery enqueue. Optional integration test with mock webhook and real YouTube URL (gated).

## 7. CI/CD (GitHub Actions)

- **Trigger:** Push to main; optional PRs to main.
- **Jobs:** Lint (e.g. Ruff); Test (Python 3.13, uv/pip, pytest, mocked Redis/Celery); Build (single Docker image). Optional integration job or flag.
- **No deploy step** in this design; deployment manual or separate.
- **Cache:** Python deps (uv/pip); Docker BuildKit/cache. Python version: **3.13**.
