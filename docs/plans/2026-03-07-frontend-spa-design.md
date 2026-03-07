# Frontend SPA Design

## Goal

Add a browser-based single-page app to Aqua Whisper that lets users paste a YouTube URL and receive the transcript. Served by the same FastAPI instance.

## Architecture

- Single `static/index.html` with Tailwind CDN and vanilla JS
- Two new unauthenticated API endpoints enable a polling flow
- Task results stored in Redis with 1-hour TTL

### Data Flow

1. User pastes YouTube URL and clicks Submit
2. Frontend POSTs to `POST /ui/transcript` with `{ "video_url": "..." }`
3. Backend validates URL, enqueues Celery task, returns `{ "task_id": "..." }`
4. Frontend polls `GET /ui/transcript/{task_id}` every 3 seconds
5. Worker runs transcript pipeline, stores result in Redis
6. Frontend receives terminal status and displays transcript or error

### New Endpoints

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/` | None | Serve `static/index.html` |
| POST | `/ui/transcript` | None | Accept `video_url`, enqueue task, return `task_id` |
| GET | `/ui/transcript/{task_id}` | None | Poll for task result |

### Backend Modules

- `app/store.py` -- Redis get/set for task results (`ui:task:{task_id}` key, JSON value, 1hr TTL)
- `app/tasks.py` -- New `run_transcript_pipeline_ui` task (stores in Redis, no webhook)
- `app/schemas.py` -- New `UITranscriptRequest` (just `video_url`)

### Design System

- Dark theme: bg `#0F172A`, surface `#1E293B`, text `#F8FAFC`, accent `#22C55E`
- Typography: Inter (Google Fonts)
- Pattern: Minimal single-column, centered
- Transitions: 200ms on hover states

### Error Handling

- Invalid YouTube URL: validated client-side and server-side, user-friendly message
- Pipeline failure: stored as `{ "status": "failed", "error": "..." }`, displayed in red
- Network failure: caught by fetch, shown as error
- Timeout: frontend stops polling after 5 minutes

## Decisions

- **Single HTML file**: No build step, minimal complexity, appropriate for scope
- **Separate UI task**: Keeps existing webhook-based task untouched
- **Redis storage**: Already a project dependency, natural fit for ephemeral results
- **No auth on UI endpoints**: Frontend is a public-facing tool served by the app itself
