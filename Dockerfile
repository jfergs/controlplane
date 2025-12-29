# syntax=docker/dockerfile:1

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VIRTUALENVS_CREATE=false

WORKDIR /app

RUN --mount=type=cache,target=/var/cache/apt \
    apt-get update && apt-get install -y --no-install-recommends build-essential && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY controlplane_server controlplane_server

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-compile --upgrade pip && \
    pip install --no-compile .

EXPOSE 8000

ENV CONTROLPLANE_TOKEN=""

CMD ["uvicorn", "controlplane_server.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
