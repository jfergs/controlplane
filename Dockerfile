# syntax=docker/dockerfile:1

FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"

COPY pyproject.toml README.md ./
COPY controlplane_server controlplane_server

RUN pip install --no-compile --upgrade pip && \
    pip install --no-compile .

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LOG_LEVEL="info" \
    CONTROLPLANE_TOKEN=""

WORKDIR /app

COPY --from=builder /venv /venv
COPY pyproject.toml README.md ./
COPY controlplane_server controlplane_server

ENV PATH="/venv/bin:$PATH"

RUN addgroup --system app && adduser --system --ingroup app app \
    && chown -R app:app /app

USER app

EXPOSE 8000

CMD ["uvicorn", "controlplane_server.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]
