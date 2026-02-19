# aqua-whisper Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement an async FastAPI microservice that accepts a YouTube URL and webhook, enqueues a Celery task to obtain a transcript (yt-dlp subs or Whisper fallback), and POSTs the result to the webhook once.

**Architecture:** FastAPI validates API key and YouTube URL, enqueues task to Redis (existing instance). Celery worker runs pipeline: manual subs → auto subs → Whisper; cleans up temp files; POSTs JSON to webhook once. Single Docker image; Python 3.13.

**Tech Stack:** Python 3.13, FastAPI, Celery, Redis (broker only), yt-dlp, FFmpeg, faster-whisper (or whisper CLI), Docker, GitHub Actions (Ruff, pytest).

**Reference:** Design in `docs/plans/2025-02-19-aqua-whisper-design.md`.

---

## Task 1: Project layout and dependencies

**Files:**
- Create: `pyproject.toml`
- Create: `app/__init__.py`
- Create: `tests/__init__.py`

**Step 1:** Create `pyproject.toml` with Python 3.13, FastAPI, uvicorn, celery[redis], redis, httpx, pydantic-settings. Dev: pytest, pytest-asyncio, ruff. Script/entry points optional.

**Step 2:** Create empty `app/__init__.py` and `tests/__init__.py`.

**Step 3:** From repo root run: `uv sync` (or `pip install -e ".[dev]"`). Expected: deps install.

**Step 4:** Commit.

```bash
git add pyproject.toml app/__init__.py tests/__init__.py
git commit -m "chore: add Python 3.13 project and deps"
```

---

## Task 2: YouTube URL validation (unit test first)

**Files:**
- Create: `tests/test_youtube_url.py`
- Create: `app/youtube.py`

**Step 1: Write the failing test**

In `tests/test_youtube_url.py`: function `is_youtube_url(url: str) -> bool`. Tests: valid `https://www.youtube.com/watch?v=...`, `https://youtu.be/...` → True; `https://vimeo.com/...`, `not-a-url`, empty string → False.

**Step 2:** Run `pytest tests/test_youtube_url.py -v`. Expected: FAIL (module/function missing).

**Step 3:** Implement `app/youtube.py` with `is_youtube_url` using a simple regex or allowed-host check (youtube.com, youtu.be).

**Step 4:** Run `pytest tests/test_youtube_url.py -v`. Expected: PASS.

**Step 5:** Commit.

```bash
git add tests/test_youtube_url.py app/youtube.py
git commit -m "feat: add YouTube URL validation"
```

---

## Task 3: API key dependency (unit test first)

**Files:**
- Create: `app/config.py` (pydantic-settings: API_KEY, REDIS_URL)
- Create: `app/auth.py` (dependency that reads header, compares to settings, raises 401)
- Create: `tests/test_auth.py` (mock dependency or test client with header)

**Step 1:** Write failing test: request without key → 401; with wrong key → 401; with correct key → pass (e.g. 404 for missing route or 202 once route exists).

**Step 2:** Run test. Expected: FAIL.

**Step 3:** Implement config and auth dependency; plug into a minimal route (e.g. GET /health that requires key for consistency, or a stub POST /transcript). Per design, health can be unauthenticated; so add a small protected route for test or test POST /transcript later.

**Step 4:** Run test. Expected: PASS.

**Step 5:** Commit.

```bash
git add app/config.py app/auth.py tests/test_auth.py
git commit -m "feat: add API key auth dependency"
```

---

## Task 4: POST /transcript request body and validation (TDD)

**Files:**
- Create: `app/schemas.py` (Pydantic: video_url, webhook_url)
- Modify: `app/main.py` (FastAPI app, POST /transcript returning 202 + task_id placeholder; use auth and youtube validation)
- Create: `tests/test_transcript_api.py`

**Step 1:** Write tests: valid body + valid YouTube URL + valid API key → 202 and JSON with `task_id`; missing video_url or webhook_url → 400; non-YouTube URL → 400; invalid API key → 401. Mock Celery task enqueue.

**Step 2:** Run tests. Expected: FAIL.

**Step 3:** Implement schemas, app with POST /transcript: validate body, validate YouTube URL, enqueue task (Celery mock or real apply_async), return 202 and `{"task_id": "<uuid>"}`. Generate task_id (uuid4) and pass to task args.

**Step 4:** Run tests. Expected: PASS.

**Step 5:** Commit.

```bash
git add app/schemas.py app/main.py tests/test_transcript_api.py
git commit -m "feat: add POST /transcript with validation and task enqueue"
```

---

## Task 5: Celery app and task skeleton

**Files:**
- Create: `app/celery_app.py` (Celery with broker=REDIS_URL, no result backend)
- Create: `app/tasks.py` (single task `run_transcript_pipeline(task_id, video_url, webhook_url)` that for now only POSTs a stub payload to webhook_url)
- Modify: `app/main.py` (import task from app.tasks and call task.apply_async(args=[task_id, body.video_url, body.webhook_url]))

**Step 1:** Integration test optional: start Redis (or use fixture), enqueue task, assert webhook received (mock server). Or defer to later; ensure unit tests mock apply_async and only check that apply_async was called with correct args.

**Step 2:** Implement Celery app and task. Task: POST to webhook_url with `{"task_id": task_id, "status": "success", "source": "manual", "transcript": "WEBVTT\n\n"}` for minimal run. Use httpx in task.

**Step 3:** Run existing tests; optional manual run with Redis. Expected: unit tests PASS.

**Step 4:** Commit.

```bash
git add app/celery_app.py app/tasks.py app/main.py
git commit -m "feat: add Celery task and webhook POST skeleton"
```

---

## Task 6: Worker pipeline — manual and auto subtitles (TDD)

**Files:**
- Create: `app/pipeline.py` (function `get_transcript(video_url: str) -> tuple[str, str]` returning (source, vtt_content) or raising)
- Create: `tests/test_pipeline.py` (mock subprocess/yt-dlp: manual sub exists → ("manual", "..."); no manual, auto exists → ("auto", "..."); neither → raise)

**Step 1:** Write tests: when yt-dlp (mocked) writes manual .vtt, get_transcript returns ("manual", vtt_body); when only auto .vtt, returns ("auto", vtt_body); when neither, raises.

**Step 2:** Run tests. Expected: FAIL.

**Step 3:** Implement get_transcript: run yt-dlp --write-sub --skip-download to temp dir; if .vtt present, read and return ("manual", content). Else run --write-auto-sub --skip-download; if .vtt present return ("auto", content). Else raise NoSubtitlesError or similar.

**Step 4:** Run tests. Expected: PASS.

**Step 5:** Commit.

```bash
git add app/pipeline.py tests/test_pipeline.py
git commit -m "feat: pipeline manual and auto subtitles via yt-dlp"
```

---

## Task 7: Worker pipeline — Whisper fallback and cleanup

**Files:**
- Modify: `app/pipeline.py` (after auto fails: download audio with yt-dlp -x, run whisper/faster-whisper to VTT, delete temp files in try/finally, return ("whisper", vtt_content))
- Modify: `tests/test_pipeline.py` (mock: no subs, then mock audio download and whisper output; assert source "whisper" and cleanup called)

**Step 1:** Write failing test for Whisper path and cleanup.

**Step 2:** Run tests. Expected: FAIL.

**Step 3:** Implement: in get_transcript, after auto fails, create temp dir, yt-dlp -x --audio-format mp3, run whisper (CLI or faster-whisper) with model base and output_format vtt, read VTT, then in finally delete temp files. Return ("whisper", content).

**Step 4:** Run tests. Expected: PASS.

**Step 5:** Commit.

```bash
git add app/pipeline.py tests/test_pipeline.py
git commit -m "feat: Whisper fallback and temp cleanup in pipeline"
```

---

## Task 8: Wire pipeline into Celery task and webhook payload

**Files:**
- Modify: `app/tasks.py` (call get_transcript(video_url); on success POST webhook with task_id, status success, source, transcript; on exception POST webhook with status failed and error message; wrap in try/finally for cleanup if needed inside pipeline)

**Step 1:** Test: unit test with mocked get_transcript and mocked httpx: success case POST body has source and transcript; failure case POST body has status failed and error.

**Step 2:** Run tests. Expected: PASS (or add test first then implement).

**Step 3:** Implement task body: get_transcript → build payload → POST; except → build error payload → POST. Single POST attempt, no retries.

**Step 4:** Commit.

```bash
git add app/tasks.py tests/test_tasks.py
git commit -m "feat: wire pipeline to task and webhook payload"
```

---

## Task 9: GET /health

**Files:**
- Modify: `app/main.py` (GET /health returns 200; optional: ping Redis and return 503 if unreachable)

**Step 1:** Test in tests: GET /health → 200.

**Step 2:** Implement. Commit.

```bash
git add app/main.py tests/test_health.py
git commit -m "feat: add GET /health"
```

---

## Task 10: Dockerfile (single image)

**Files:**
- Create: `Dockerfile` (Python 3.13 base; install system deps: ffmpeg; install yt-dlp, app deps; copy app; CMD for API; document worker with `celery -A app.celery_app worker --loglevel=info --concurrency=1`)

Use single stage; optionally multi-stage to reduce size. Image must include FastAPI app, Celery worker code, yt-dlp, FFmpeg, Whisper/faster-whisper.

**Step 1:** Build image. Expected: success.

**Step 2:** Commit.

```bash
git add Dockerfile
git commit -m "chore: add Dockerfile for API and worker"
```

---

## Task 11: Docker Compose (api + worker; Redis external)

**Files:**
- Create: `compose.yaml` (services: api, worker; same image; env REDIS_URL point to host or external Redis; no redis service. Document that Redis is existing instance.)

**Step 1:** Commit.

```bash
git add compose.yaml
git commit -m "chore: add Compose for api and worker (Redis external)"
```

---

## Task 12: GitHub Actions — lint and test

**Files:**
- Create: `.github/workflows/ci.yml` (on push to main; job lint: Ruff; job test: Python 3.13, uv sync, pytest; cache deps)

**Step 1:** Run Ruff and pytest locally. Push or run workflow. Expected: lint and test pass.

**Step 2:** Commit.

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add lint and test workflow"
```

---

## Task 13: GitHub Actions — build image

**Files:**
- Modify: `.github/workflows/ci.yml` (job build: build Docker image; optional tag with sha)

**Step 1:** Run workflow. Expected: build succeeds.

**Step 2:** Commit.

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add Docker build job"
```

---

## Execution Handoff

Plan complete and saved to `docs/plans/2025-02-19-aqua-whisper.md`. Two execution options:

**1. Subagent-Driven (this session)** — I dispatch fresh subagent per task, review between tasks, fast iteration.

**2. Parallel Session (separate)** — Open new session with executing-plans, batch execution with checkpoints.

Which approach?
