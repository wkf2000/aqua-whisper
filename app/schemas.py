"""Pydantic request/response schemas."""

from pydantic import BaseModel


class TranscriptRequest(BaseModel):
    """Request body for POST /transcript."""

    video_url: str
    webhook_url: str
    author: str = "unknown"


class UITranscriptRequest(BaseModel):
    """Request body for POST /ui/transcript (no webhook, no auth)."""

    video_url: str
