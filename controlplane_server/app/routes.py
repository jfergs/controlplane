from __future__ import annotations

import platform

from fastapi import APIRouter, Header

from .config import APP_NAME
from .security import require_token
from .system import (
    cpu_temp_c,
    disk_usage,
    load_average,
    memory_stats,
    network_io_counters,
    uptime_seconds,
)

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
        "uptime_sec": uptime_seconds(),
        "disk_root": disk_usage("/"),
        "cpu_temp_c": cpu_temp_c(),
        "memory": memory_stats(),
        "load_avg": load_average(),
        "net_io": network_io_counters(),
    }
