"""API key auth dependency."""

from fastapi import Header, HTTPException

from app.config import settings


async def require_api_key(
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
) -> None:
    """Validate API key from Authorization Bearer or X-API-Key header. Raises 401 if missing or wrong."""
    token: str | None = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:].strip()
    elif x_api_key:
        token = x_api_key.strip()
    if not token or token != settings.API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
