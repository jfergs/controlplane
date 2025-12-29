from __future__ import annotations

import os
import platform
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel

try:
    import psutil
except Exception:  # pragma: no cover - psutil may be absent in minimal envs
    psutil = None

from .config import get_thresholds


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


def memory_stats() -> dict[str, float | None]:
    """Return memory stats using psutil if available."""
    if psutil:
        try:
            mem = psutil.virtual_memory()
            return {
                "total_gb": round(mem.total / (1024**3), 2),
                "available_gb": round(mem.available / (1024**3), 2),
                "percent": round(mem.percent, 2),
            }
        except Exception:
            pass
    return {"total_gb": None, "available_gb": None, "percent": None}


def load_average() -> dict[str, float | None]:
    """Return 1/5/15 minute load averages where supported."""
    try:
        one, five, fifteen = os.getloadavg()
        return {"1m": round(one, 2), "5m": round(five, 2), "15m": round(fifteen, 2)}
    except Exception:
        return {"1m": None, "5m": None, "15m": None}


def network_io_counters() -> dict[str, int | None]:
    """Return bytes sent/received using psutil if available."""
    if psutil:
        try:
            counters = psutil.net_io_counters()
            return {"bytes_sent": counters.bytes_sent, "bytes_recv": counters.bytes_recv}
        except Exception:
            pass
    return {"bytes_sent": None, "bytes_recv": None}


class DiskInfo(BaseModel):
    total_gb: float | None
    used_gb: float | None
    free_gb: float | None


class MemoryInfo(BaseModel):
    total_gb: float | None
    available_gb: float | None
    percent: float | None


class LoadInfo(BaseModel):
    one_m: float | None
    five_m: float | None
    fifteen_m: float | None

    def as_dict(self) -> dict[str, float | None]:
        return {"1m": self.one_m, "5m": self.five_m, "15m": self.fifteen_m}


class NetIOInfo(BaseModel):
    bytes_sent: int | None
    bytes_recv: int | None


class StatusResponse(BaseModel):
    uptime_sec: int
    disk_root: DiskInfo
    cpu_temp_c: float | None
    memory: MemoryInfo
    load_avg: LoadInfo
    net_io: NetIOInfo
    warnings: list[str]


def status_payload() -> dict[str, Any]:
    load = load_average()
    thresholds = get_thresholds()
    warnings: list[str] = []

    disk = disk_usage("/")
    free_gb = disk.get("free_gb")
    if free_gb is not None and free_gb < thresholds.disk_free_gb_warn:
        warnings.append(f"Low disk free space: {free_gb} GB < {thresholds.disk_free_gb_warn} GB")

    mem = memory_stats()
    mem_percent = mem.get("percent")
    if mem_percent is not None and mem_percent > thresholds.mem_percent_warn:
        warnings.append(f"High memory usage: {mem_percent}% > {thresholds.mem_percent_warn}%")

    load_avg = load_average()
    load_warns = [
        ("1m", load_avg.get("1m"), thresholds.load_1m_warn),
        ("5m", load_avg.get("5m"), thresholds.load_5m_warn),
        ("15m", load_avg.get("15m"), thresholds.load_15m_warn),
    ]
    for label, value, limit in load_warns:
        if value is not None and value > limit:
            warnings.append(f"High load {label}: {value} > {limit}")

    model = StatusResponse(
        uptime_sec=uptime_seconds(),
        disk_root=DiskInfo(**disk),
        cpu_temp_c=cpu_temp_c(),
        memory=MemoryInfo(**mem),
        load_avg=LoadInfo(one_m=load.get("1m"), five_m=load.get("5m"), fifteen_m=load.get("15m")),
        net_io=NetIOInfo(**network_io_counters()),
        warnings=warnings,
    )
    data = model.model_dump()
    # Replace load_avg with aliased keys
    data["load_avg"] = model.load_avg.as_dict()
    return data
