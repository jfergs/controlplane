# ControlPlane

ControlPlane is a lightweight FastAPI-based control plane for monitoring and
controlled automation in macOS and Raspberry Pi home lab environments.

## API

- `GET /api/status` (requires `Authorization: Bearer <CONTROLPLANE_TOKEN>`) returns host info,
  disk usage, CPU temp (when available), memory stats, load average, and network I/O counters.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e .[dev]
```

## Running

Set an API token the server will enforce on protected endpoints:

```bash
export CONTROLPLANE_TOKEN="your-long-token"
just serve
```

## Tests and linting

```bash
just test     # pytest
just fmt      # ruff format + fix
```
