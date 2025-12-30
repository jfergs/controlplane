# ControlPlane

ControlPlane is a lightweight FastAPI-based control plane for monitoring and
controlled automation in macOS and Raspberry Pi home lab environments.

## Install (Python host)

Requires Python 3.12+. On Raspberry Pi or macOS:

```bash
git clone https://github.com/jfergs/controlplane.git
cd controlplane
python -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e .[dev]
export CONTROLPLANE_TOKEN="your-long-token"
LOG_LEVEL=info python -m uvicorn controlplane_server.app.main:app --host 0.0.0.0 --port 8000
```

Use `just serve` if you already have the venv active.

## Install (Docker / Compose)

Build and run locally (requires `docker`):

```bash
just docker-build
CONTROLPLANE_TOKEN=your-long-token just docker-run
```

Compose option:

```bash
mkdir -p data
CONTROLPLANE_TOKEN=your-long-token \
CONTROLPLANE_SESSION_SECRET=$(openssl rand -hex 16) \
CONTROLPLANE_DB_PATH=/data/.controlplane.db \
CONTROLPLANE_ENDPOINT_RETENTION_SEC=0 \
CONTROLPLANE_RATE_LIMIT=100/min \
docker compose up --build
```
The compose file mounts `./data` to `/data` in the container; adjust envs as needed.

Redeploy/update with the latest image (after pulling from GitHub):

```bash
git pull origin main
CONTROLPLANE_TOKEN=your-long-token \
CONTROLPLANE_SESSION_SECRET=$(openssl rand -hex 16) \
CONTROLPLANE_DB_PATH=/data/.controlplane.db \
CONTROLPLANE_ENDPOINT_RETENTION_SEC=0 \
CONTROLPLANE_RATE_LIMIT=100/min \
docker compose pull && docker compose up -d
```

## Tests and linting

```bash
just test     # pytest
just fmt      # ruff format + fix
```

## API / Endpoints

- `GET /` — service info
- `GET /health` — liveness
- `GET /api/status` (requires `Authorization: Bearer <CONTROLPLANE_TOKEN>`) — host/os/python,
  uptime, disk, CPU temp (if available), memory, load avg, net I/O, Wi-Fi (macOS/Linux), battery
  (macOS/Linux), warnings, thresholds applied
- `GET /metrics` — Prometheus metrics
- `POST /api/push-status` — endpoints push metrics (same shape as `/api/status`) using the bearer token
- `GET /api/endpoints` — list pushed endpoints; `GET /api/endpoints/{endpoint_id}` — detail
- `DELETE /api/endpoints/{endpoint_id}` — remove a pushed endpoint
- `GET /dashboard` — built-in dark dashboard (enter your bearer token in the UI to view status)

## CLI

Use the CLI to hit `/api/status` with your token from Keychain:

```bash
python -m controlplane_cli --url http://localhost:8000 --account "$(whoami)"
python -m controlplane_cli --json            # JSON output
python -m controlplane_cli --watch --interval 10 --fail-on-warnings
python -m controlplane_cli token-set --token "$CONTROLPLANE_TOKEN"
```

## Observability

- Logging: set `LOG_LEVEL` (default `INFO`); logs emit JSON lines.
- Metrics: Prometheus endpoint exposed at `/metrics` when the server is running, including load/memory/disk plus Wi-Fi and battery details on macOS/Linux when available (fields are `None` if not supported). Request metrics are exported with path/status labels.

## Security / deployment

- Keep the API behind TLS (reverse proxy such as nginx/Caddy/Traefik) and restrict exposure to trusted networks.
- The bearer token protects `/api/status`, `/api/push-status`, and `/api/endpoints*`; rotate it as needed and restart the server/agents.
- CORS is off by default; enable only for trusted origins if exposing the dashboard across domains.
- Rate limiting (per-client, best-effort) can be enabled via `CONTROLPLANE_RATE_LIMIT` (e.g., `100/min`). Consider enforcing limits at the reverse proxy, too.
- Database path can be overridden with `CONTROLPLANE_DB_PATH`; endpoint retention (in seconds) via `CONTROLPLANE_ENDPOINT_RETENTION_SEC`.
- Dashboard login: first visit to `/login` lets you set username/password (stored in `.controlplane_login.json`). Sessions use `CONTROLPLANE_SESSION_SECRET`; rotate it to invalidate sessions.
## CI

GitHub Actions (`.github/workflows/ci.yml`) runs ruff and pytest on push/PR to main.
Tag builds also publish a Docker image to GHCR at `ghcr.io/<org>/<repo>/controlplane:<tag>`.
