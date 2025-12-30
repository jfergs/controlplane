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
- `GET /dashboard` — built-in dark dashboard (protected by username/password you set on first visit). Dashboard data uses your session; the bearer token is only needed to generate agent install scripts.

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

- Always serve behind TLS (nginx/Caddy/Traefik). Restrict exposure to trusted networks.
- Dashboard: username/password set on first visit to `/login`; session cookie is signed with `CONTROLPLANE_SESSION_SECRET` and has TTL `CONTROLPLANE_SESSION_TTL_SEC` (default 86400). CSRF is enforced for destructive dashboard actions.
- API bearer token protects `/api/status`, `/api/push-status`, `/api/endpoints*`; rotate it as needed and restart the server/agents. Dashboard does not expose the bearer; it proxies through the session.
- Rate limiting (per-client, best-effort) can be enabled via `CONTROLPLANE_RATE_LIMIT` (e.g., `100/min`). Also consider limits at the reverse proxy.
- Database path can be overridden with `CONTROLPLANE_DB_PATH`; endpoint retention (seconds) via `CONTROLPLANE_ENDPOINT_RETENTION_SEC`.
- CORS is off by default; enable only for trusted origins if exposing the dashboard across domains.

### TLS reverse proxy example (nginx)

```nginx
server {
  listen 443 ssl;
  server_name controlplane.example.com;

  ssl_certificate     /etc/letsencrypt/live/controlplane.example.com/fullchain.pem;
  ssl_certificate_key /etc/letsencrypt/live/controlplane.example.com/privkey.pem;

  location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
  }
}
```

### TLS reverse proxy example (Caddyfile)

```
controlplane.example.com {
  reverse_proxy 127.0.0.1:8000
}
```
## CI

GitHub Actions (`.github/workflows/ci.yml`) runs ruff and pytest on push/PR to main.
Tag builds also publish a Docker image to GHCR at `ghcr.io/<org>/<repo>/controlplane:<tag>`.
