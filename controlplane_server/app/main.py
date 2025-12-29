from __future__ import annotations

import platform
import shutil
import subprocess
import time

from fastapi import FastAPI

app = FastAPI(title="ControlPlane", version="0.2.0")


def _run(cmd: list[str]) -> str:
    """Run a command and return stdout (best-effort)."""
    try:
        return subprocess.check_output(cmd, text=True).strip()
    except Exception:
        return ""


def _uptime_seconds() -> int:
    # macOS: sysctl kern.boottime gives boot time
    if platform.system() == "Darwin":
        out = _run(["sysctl", "-n", "kern.boottime"])
        # Example: { sec = 1703860000, usec = 0 } ...
        if "sec" in out:
            try:
                sec_part = out.split("sec =")[1].split(",")[0].strip()
                boot = int(sec_part)
                return int(time.time() - boot)
            except Exception:
                pass
    # Linux: read /proc/uptime
    try:
        with open("/proc/uptime", encoding="utf-8") as f:
            return int(float(f.read().split()[0]))
    except Exception:
        return 0


def _cpu_temp_c() -> float | None:
    # Raspberry Pi / many Linux: thermal zone
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
def status():
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
