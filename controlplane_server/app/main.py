from __future__ import annotations

from fastapi import FastAPI

from .config import APP_NAME, APP_VERSION
from .routes import router


def create_app() -> FastAPI:
    app = FastAPI(title=APP_NAME, version=APP_VERSION)
    app.include_router(router)
    return app


app = create_app()
