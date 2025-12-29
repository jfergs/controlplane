from __future__ import annotations

import platform
import shutil
import subprocess
import time
from pathlib import Path


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.check_output(cmd, text=True).strip()
    except Exception:
        return ""


def uptime_seconds() -> int:
    """Return uptime in seconds using platform-specific sources."""
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


def cpu_temp_c() -> float | None:
    """Read CPU temperature in Celsius if available."""
    for path in ("/sys/class/thermal/thermal_zone0/temp",):
        try:
            with open(path, encoding="utf-8") as f:
                milli = int(f.read().strip())
            return round(milli / 1000.0, 1)
        except Exception:
            pass
    return None


def disk_usage(path: str | Path = "/") -> dict[str, float]:
    """Return disk usage details (in GB) for a filesystem path."""
    total, used, free = shutil.disk_usage(path)
    return {
        "total_gb": round(total / (1024**3), 2),
        "used_gb": round(used / (1024**3), 2),
        "free_gb": round(free / (1024**3), 2),
    }
