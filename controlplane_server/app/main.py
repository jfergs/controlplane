from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator, metrics

from .config import APP_NAME, APP_VERSION
from .logging_config import configure_logging
from .logging_middleware import logging_middleware
from .rate_limit import build_rate_limiter_from_env, rate_limit_middleware
from .routes import router


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title=APP_NAME, version=APP_VERSION)
    app.middleware("http")(logging_middleware)
    limiter = build_rate_limiter_from_env()
    if limiter:
        app.middleware("http")(rate_limit_middleware(limiter))
    app.include_router(router)
    instrumentator = Instrumentator()
    instrumentator.add(metrics.requests()).add(metrics.request_size()).add(metrics.response_size())
    instrumentator.instrument(app, metric_namespace="controlplane").expose(
        app, include_in_schema=False
    )
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")
    return app


app = create_app()
