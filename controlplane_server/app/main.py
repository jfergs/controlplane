from __future__ import annotations

import os
import platform
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

app = FastAPI(title="ControlPlane", version="0.2.0")

REPO_ROOT = Path(__file__).resolve().parents[2]  # .../controlplane_server/app/main.py -> repo root
CONFIG_PATH = REPO_ROOT / "controlplane.yaml"
RUNLOG_PATH = REPO_ROOT / "runlog.jsonl"

API_TOKEN = os.environ.get("CONTROLPLANE_TOKEN", "")


def require_token(authorization: str | None):
    if not API_TOKEN:
        raise HTTPException(status_code=500, detail="Server missing CONTROLPLANE_TOKEN env var")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    if authorization.split(" ", 1)[1] != API_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid token")


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise HTTPException(status_code=500, detail=f"Missing config: {CONFIG_PATH}")
    data = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    if "jobs" not in data or not isinstance(data["jobs"], dict):
        raise HTTPException(status_code=500, detail="Config must contain top-level 'jobs' mapping")
    return data


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
            milli = int(Path(path).read_text(encoding="utf-8").strip())
            return round(milli / 1000.0, 1)
        except Exception:
            pass
    return None


def append_runlog(entry: dict[str, Any]) -> None:
    RUNLOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with RUNLOG_PATH.open("a", encoding="utf-8") as f:
        f.write(yaml.safe_dump(entry, sort_keys=False).strip().replace("\n", "\\n") + "\n")


class RunReq(BaseModel):
    job: str


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


@app.get("/api/jobs")
def list_jobs(authorization: str | None = Header(default=None)):
    require_token(authorization)
    cfg = load_config()
    return {"jobs": sorted(cfg["jobs"].keys())}


@app.post("/api/run")
def run_job(req: RunReq, authorization: str | None = Header(default=None)):
    require_token(authorization)
    cfg = load_config()
    jobs = cfg["jobs"]
    if req.job not in jobs:
        raise HTTPException(status_code=404, detail="Unknown job")

    spec = jobs[req.job]
    cmd = spec.get("cmd")
    timeout = int(spec.get("timeout_sec", 60))

    if not isinstance(cmd, list) or not all(isinstance(x, str) for x in cmd):
        raise HTTPException(
            status_code=500, detail=f"Job '{req.job}' cmd must be a list of strings"
        )

    start = time.time()
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            cwd=str(REPO_ROOT),
        )
        result = {
            "job": req.job,
            "exit_code": p.returncode,
            "seconds": round(time.time() - start, 3),
            "stdout_tail": (p.stdout or "")[-2000:],
            "stderr_tail": (p.stderr or "")[-2000:],
        }
        append_runlog({"ts": int(time.time()), **result})
        return result
    except subprocess.TimeoutExpired as err:
        result = {"job": req.job, "exit_code": None, "seconds": timeout, "error": "timeout"}
        append_runlog({"ts": int(time.time()), **result})
        raise HTTPException(status_code=408, detail="Job timed out") from err
