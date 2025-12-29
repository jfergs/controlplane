from __future__ import annotations

import os
import platform
import shutil
import subprocess
import time

from fastapi import FastAPI, Header, HTTPException

app = FastAPI(title="ControlPlane", version="0.3.0")

API_TOKEN = os.environ.get("CONTROLPLANE_TOKEN", "")


def require_token(authorization: str | None) -> None:
    if not API_TOKEN:
        raise HTTPException(status_code=500, detail="Server missing CONTROLPLANE_TOKEN")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1]
    if token != API_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid token")


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.check_output(cmd, text=True).strip()
    except Exception:
        return ""


def _uptime_seconds() -> int:
    if platform.system() == "Darwin":
        out = _run(["sysctl", "-n", "kern.boottime"])
        if "sec" in out:
            try:
                sec_part = out.split("sec =")[1].split(",")[0].strip()
                boot = int(sec_part)
                return int(time.time() - boot)
            except Exception:
                pass
    try:
        with open("/proc/uptime", encoding="utf-8") as f:
            return int(float(f.read().split()[0]))
    except Exception:
        return 0


def _cpu_temp_c() -> float | None:
    for path in ("/sys/class/thermal/thermal_zone0/temp",):
        try:
            with open(path, encoding="utf-8") as f:
                milli = int(f.read().strip())
            return round(milli / 1000.0, 1)
        except Exception:
            pass
    return None


@app.get("/")
def root():
    return {"name": "ControlPlane", "status": "ok"}


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/api/status")
def status(authorization: str | None = Header(default=None)):
    require_token(authorization)
    total, used, free = shutil.disk_usage("/")
    return {
        "host": platform.node(),
        "os": platform.platform(),
        "python": platform.python_version(),
        "uptime_sec": _uptime_seconds(),
        "disk_root": {
            "total_gb": round(total / (1024**3), 2),
            "used_gb": round(used / (1024**3), 2),
            "free_gb": round(free / (1024**3), 2),
        },
        "cpu_temp_c": _cpu_temp_c(),
    }
