"""FastAPI app with API key–protected routes."""

from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.auth import require_api_key
from app.schemas import TranscriptRequest
from app.tasks import run_transcript_pipeline
from app.youtube import is_youtube_url

app = FastAPI()


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
