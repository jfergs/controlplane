from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import HTTPException, Request


class RateLimiter:
    def __init__(self, limit: int, window_seconds: int):
        self.limit = limit
        self.window = window_seconds
        self.buckets: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.time()
        bucket = self.buckets[key]
        while bucket and bucket[0] <= now - self.window:
            bucket.popleft()
        if len(bucket) >= self.limit:
            return False
        bucket.append(now)
        return True


def parse_rate_limit(env_value: str | None) -> tuple[int, int] | None:
    if not env_value:
        return None
    try:
        value, unit = env_value.split("/")
        limit = int(value)
        unit = unit.strip().lower()
        if unit in {"s", "sec", "second"}:
            return limit, 1
        if unit in {"m", "min", "minute"}:
            return limit, 60
        if unit in {"h", "hr", "hour"}:
            return limit, 3600
    except Exception:
        return None
    return None


def rate_limit_middleware(limiter: RateLimiter) -> Callable:
    async def middleware(request: Request, call_next):
        client = request.client.host if request.client else "unknown"
        if not limiter.allow(client):
            raise HTTPException(status_code=429, detail="Rate limit exceeded")
        return await call_next(request)

    return middleware


def build_rate_limiter_from_env() -> RateLimiter | None:
    limit_spec = os.environ.get("CONTROLPLANE_RATE_LIMIT")
    parsed = parse_rate_limit(limit_spec)
    if not parsed:
        return None
    limit, window = parsed
    return RateLimiter(limit, window)
