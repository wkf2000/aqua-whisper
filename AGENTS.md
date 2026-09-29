# AGENTS.md

## Project overview

`aqua-whisper` is a Python 3.13 FastAPI service with a Celery worker. It
downloads YouTube subtitles with `yt-dlp`, falls back to faster-whisper when
needed, and stores completed transcripts in SQLite. Redis is the Celery broker.
The unauthenticated frontend is plain HTML and browser JavaScript in `static/`.

## Environment setup

Install the required tools before making changes:

- Python 3.13
- [`uv`](https://docs.astral.sh/uv/)
- Node.js 22 and npm
- Docker and Docker Compose for container or integration work
- A reachable Redis instance for running the API and worker together

Set up a local checkout with:

```bash
uv sync --all-extras
npm ci
cp .env.example .env
```

Edit `.env` with a local `API_KEY` and `REDIS_URL`. Never commit `.env`,
credentials, downloaded Whisper models, or runtime transcript data. The
default local database location is `./data/transcripts.db`.

## Development workflow

Before editing, inspect the current worktree with `git status --short` and
preserve existing user changes. Keep changes scoped to the task. The API and
worker can be run in separate terminals:

```bash
uv run uvicorn app.main:app --reload --port 8000
uv run celery -A app.celery_app worker --loglevel=info --concurrency=1 --pool=solo
```

Use `--pool=solo` for a macOS worker because faster-whisper can trigger
Objective-C fork-safety failures. Linux and Docker can use the Compose command,
which uses Celery's default pool:

```bash
docker network create aqua-whisper-backend  # once, if it does not exist
docker compose up --build
```

The Compose file expects an external Redis and reads `.env`. It mounts
`./whisper-model` and `./data`; these directories are intentionally ignored by
Git.

## Validation

Run the narrowest relevant checks while iterating. Before submitting a change,
run the complete CI-equivalent checks:

```bash
uv run ruff check .
uv run ruff format --check .
npm run lint
uv run pytest -v
```

The Python tests live in `tests/` and are configured through `pyproject.toml`.
Frontend lint covers `static/js`; the frontend has no bundler or build step.
For HTML or static asset changes, verify both `/` and `/history` if the change
affects shared page behavior.

## Repository conventions

- Keep Python code compatible with Python 3.13 and format it with Ruff.
- Follow the existing 100-character Ruff line length and prefer type
  annotations for new functions and public data.
- Keep FastAPI route behavior and API error shapes stable unless the task
  explicitly changes the API.
- Keep transcript processing in the pipeline/task modules and persistence
  concerns in `app/db.py` or `app/store.py`; avoid duplicating database logic
  in routes.
- Use structured logging through the existing `structlog` setup. Do not log
  API keys, webhook URLs, transcript contents, or other user-provided secrets.
- Frontend pages are static HTML with Tailwind loaded from its CDN and
  JavaScript modules under `static/js/`. Match the existing dark theme and use
  the existing npm lint rules; do not introduce a framework for small UI
  changes.
- Keep dependency versions reproducible: update `uv.lock` when Python
  dependencies change and update `package-lock.json` when npm dependencies
  change.
- Add or update focused tests for behavior changes. Do not weaken or skip
  existing checks to make a change pass.

## Git and delivery

Review `git diff` and `git diff --check` before committing. Do not reset,
checkout over, clean, or delete files that may contain user work. Commit
related changes together with a concise imperative message. Pull requests
target `main` and should include the user-visible behavior, validation run,
and any deployment or configuration notes.

CI runs Ruff, frontend ESLint, and pytest for every push and pull request to
`main`. Only pushes to `main` build and publish the Docker image; deployment is
performed by CI, not from a local agent session.
