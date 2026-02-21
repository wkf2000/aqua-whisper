"""Pydantic request/response schemas."""

from pydantic import BaseModel


class TranscriptRequest(BaseModel):
    """Request body for POST /transcript."""

    video_url: str
    webhook_url: str
    author: str = "unknown"
