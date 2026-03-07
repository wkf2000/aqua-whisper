"""FastAPI app with API key–protected routes."""

from pathlib import Path
from uuid import uuid4

import structlog
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.auth import require_api_key
from app.config import settings
from app.logging_config import setup_logging
from app.schemas import TranscriptRequest, UITranscriptRequest
from app.store import get_task_result
from app.tasks import run_transcript_pipeline, run_transcript_pipeline_ui
from app.tracing import setup_tracing
from app.youtube import is_youtube_url

setup_logging(service_name="aqua-whisper-api", environment=settings.ENV)
setup_tracing(service_name="aqua-whisper-api", environment=settings.ENV)

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI()
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
logger = structlog.get_logger()


@app.middleware("http")
async def logging_middleware(request: Request, call_next):
    """Log a single structured event per request with basic metadata."""
    response = await call_next(request)
    logger.info(
        "request",
        path=request.url.path,
        method=request.method,
        status_code=response.status_code,
        client_ip=request.client.host if request.client else None,
    )
    return response


@app.exception_handler(RequestValidationError)
def validation_exception_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    """Return 400 for body validation errors (e.g. missing required fields)."""
    return JSONResponse(status_code=400, content={"detail": "Invalid request body"})


@app.get("/health")
def health() -> dict[str, str]:
    """Health check: returns 200 when API is up. No auth required."""
    return {"status": "ok"}


@app.get("/protected")
def protected(_: None = Depends(require_api_key)) -> dict[str, bool]:
    """Stub protected route for auth tests. Returns 200 with ok: true when auth passes."""
    return {"ok": True}


@app.post("/transcript", status_code=202)
def transcript(
    body: TranscriptRequest,
    _: None = Depends(require_api_key),
) -> dict[str, str]:
    """Accept video_url and webhook_url, enqueue transcript task, return 202 with task_id."""
    if not is_youtube_url(body.video_url):
        raise HTTPException(status_code=400, detail="video_url must be a YouTube URL")
    task_id = str(uuid4())
    run_transcript_pipeline.apply_async(
        args=[task_id, body.video_url, body.webhook_url, body.author]
    )
    return {"task_id": task_id}


# ── UI (unauthenticated) ────────────────────────────────────────────


@app.get("/")
def ui_index() -> FileResponse:
    """Serve the single-page frontend."""
    return FileResponse(_STATIC_DIR / "index.html")


@app.post("/ui/transcript", status_code=202)
def ui_transcript(body: UITranscriptRequest) -> dict[str, str]:
    """Accept a YouTube URL, enqueue transcript task, return task_id."""
    if not is_youtube_url(body.video_url):
        raise HTTPException(status_code=400, detail="video_url must be a YouTube URL")
    task_id = str(uuid4())
    run_transcript_pipeline_ui.apply_async(args=[task_id, body.video_url])
    return {"task_id": task_id}


@app.get("/ui/transcript/{task_id}")
def ui_transcript_status(task_id: str) -> dict:
    """Poll for a UI transcript task result."""
    result = get_task_result(task_id)
    if result is None:
        return {"status": "pending"}
    return result
