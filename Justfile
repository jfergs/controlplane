set dotenv-load := true

fmt:
    python -m ruff format .
    python -m ruff check . --fix

test:
    python -m pytest -q

serve:
    python -m uvicorn controlplane_server.app.main:app --reload --host 0.0.0.0 --port 8000

docker-build:
    docker build -t controlplane:latest .

docker-run:
    docker run --rm -p 8000:8000 -e CONTROLPLANE_TOKEN=$CONTROLPLANE_TOKEN controlplane:latest

compose:
    docker compose up --build
