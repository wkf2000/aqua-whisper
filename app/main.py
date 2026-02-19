"""FastAPI app with API key–protected routes."""

from fastapi import Depends, FastAPI

from app.auth import require_api_key

app = FastAPI()


@app.get("/protected")
def protected(_: None = Depends(require_api_key)) -> dict[str, bool]:
    """Stub protected route for auth tests. Returns 200 with ok: true when auth passes."""
    return {"ok": True}
