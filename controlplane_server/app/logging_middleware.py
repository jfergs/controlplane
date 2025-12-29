from __future__ import annotations

import json
import time
from collections.abc import Callable

from fastapi import Request, Response


async def logging_middleware(request: Request, call_next: Callable) -> Response:
    start = time.time()
    try:
        response = await call_next(request)
    except Exception as exc:  # pragma: no cover - passthrough
        duration = (time.time() - start) * 1000
        log_line(
            {
                "event": "request",
                "path": request.url.path,
                "method": request.method,
                "status": 500,
                "duration_ms": round(duration, 2),
                "error": str(exc),
            }
        )
        raise
    duration = (time.time() - start) * 1000
    log_line(
        {
            "event": "request",
            "path": request.url.path,
            "method": request.method,
            "status": response.status_code,
            "duration_ms": round(duration, 2),
        }
    )
    return response


def log_line(payload: dict) -> None:
    try:
        print(json.dumps(payload))
    except Exception:
        print(str(payload))
