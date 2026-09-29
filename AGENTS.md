
## Project overview

`aqua-whisper` is a Python 3.13 FastAPI service with a Celery worker. It
downloads YouTube subtitles with `yt-dlp`, falls back to faster-whisper when
needed, and stores completed transcripts in SQLite. Redis is the Celery broker.
The unauthenticated frontend is plain HTML and browser JavaScript in `static/`.

## Repository conventions

- Keep Python code compatible with Python 3.13, format it with Ruff, and keep it passing
  mypy strict (`uv run mypy`).
- Keep FastAPI route behavior and API error shapes stable unless the task
  explicitly changes the API.
- Keep transcript processing in the pipeline/task modules and persistence
  concerns in `app/db.py` or `app/store.py`; avoid duplicating database logic
  in routes.
- Use structured logging through the existing `structlog` setup. Do not log
  API keys, webhook URLs, transcript contents, or other user-provided secrets.

## The 7-Step Solution Ladder
Before writing or modifying any code, read the relevant context carefully. Once you understand the problem, evaluate solutions strictly in the following order and stop at the first step that works:

1. **YAGNI (Skip it):** Does this feature, abstraction, or defensive layer genuinely need to exist right now? If no, do not write it.
2. **Reuse Existing Code:** Is this logic already solved in the codebase? Reuse existing utilities, helpers, or components instead of writing new ones.
3. **Language Standard Library:** Does the language's standard library or built-in runtime API already do this? Use it directly.
4. **Native Platform Capabilities:** Can the platform/runtime handle this natively (e.g., standard HTML elements, native browser APIs, OS-level utilities)? Prefer native over custom.
5. **Existing Dependencies:** Can an already-installed dependency solve this cleanly without adding new packages? Use it. Never introduce a new package if an existing one or a few clean lines suffice.
