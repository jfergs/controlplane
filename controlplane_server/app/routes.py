from __future__ import annotations

import platform

from fastapi import APIRouter, Header

from .config import APP_NAME
from .schemas import HealthResponse, RootResponse, StatusResponse
from .security import require_token
from .system import status_payload

router = APIRouter()


@router.get("/", response_model=RootResponse, summary="Service info")
def root():
    return RootResponse(name=APP_NAME, status="ok")


@router.get("/health", response_model=HealthResponse, summary="Liveness check")
def health():
    return HealthResponse(ok=True)


@router.get("/api/status", response_model=StatusResponse, summary="Host status")
def status(authorization: str | None = Header(default=None)):
    require_token(authorization)
    metrics = status_payload()
    return StatusResponse(
        host=platform.node(),
        os=platform.platform(),
        python=platform.python_version(),
        **metrics,
    )
