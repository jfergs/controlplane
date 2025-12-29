from __future__ import annotations

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from .config import APP_NAME, APP_VERSION
from .logging_config import configure_logging
from .routes import router


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title=APP_NAME, version=APP_VERSION)
    app.include_router(router)
    Instrumentator().instrument(app).expose(app, include_in_schema=False)
    return app


app = create_app()
