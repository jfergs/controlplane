from __future__ import annotations

import platform

from fastapi import APIRouter, Header

from .config import APP_NAME
from .security import require_token
from .system import status_payload

router = APIRouter()


@router.get("/")
def root():
    return {"name": APP_NAME, "status": "ok"}


@router.get("/health")
def health():
    return {"ok": True}


@router.get("/api/status")
def status(authorization: str | None = Header(default=None)):
    require_token(authorization)
    return {
        "host": platform.node(),
        "os": platform.platform(),
        "python": platform.python_version(),
        **status_payload(),
    }
