# ControlPlane

A lightweight FastAPI-based control plane for monitoring and controlled automation,
built for macOS + Raspberry Pi home lab environments.

## Dev
```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install fastapi uvicorn pytest ruff just
just test
just serve
