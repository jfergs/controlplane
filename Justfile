set dotenv-load := true

fmt:
    ruff format .
    ruff check . --fix

test:
    python -m pytest -q

serve:
    python -m uvicorn controlplane_server.app.main:app --reload --host 0.0.0.0 --port 8000
