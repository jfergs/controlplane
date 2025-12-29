from __future__ import annotations

from fastapi import Header, HTTPException

from .config import get_api_token


def require_token(authorization: str | None = Header(default=None)) -> None:
    """Validate Authorization header against the configured API token."""
    try:
        expected = get_api_token()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")

    provided = authorization.split(" ", 1)[1]
    if provided != expected:
        raise HTTPException(status_code=403, detail="Invalid token")
