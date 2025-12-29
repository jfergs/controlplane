from __future__ import annotations

import os
from dataclasses import dataclass

APP_NAME = "ControlPlane"
APP_VERSION = "0.3.0"
TOKEN_ENV_VAR = "CONTROLPLANE_TOKEN"


def get_api_token() -> str:
    """Return the bearer token expected by the API or raise if missing."""
    token = os.environ.get(TOKEN_ENV_VAR, "")
    if not token:
        raise RuntimeError(f"Server missing {TOKEN_ENV_VAR}")
    return token


@dataclass(frozen=True)
class Thresholds:
    disk_free_gb_warn: float
    mem_percent_warn: float
    load_1m_warn: float
    load_5m_warn: float
    load_15m_warn: float


def get_thresholds() -> Thresholds:
    """Load warning thresholds from environment (with sane defaults)."""
    return Thresholds(
        disk_free_gb_warn=float(os.environ.get("CONTROLPLANE_DISK_FREE_GB_WARN", "1.0")),
        mem_percent_warn=float(os.environ.get("CONTROLPLANE_MEM_PERCENT_WARN", "90.0")),
        load_1m_warn=float(os.environ.get("CONTROLPLANE_LOAD_1M_WARN", "4.0")),
        load_5m_warn=float(os.environ.get("CONTROLPLANE_LOAD_5M_WARN", "3.0")),
        load_15m_warn=float(os.environ.get("CONTROLPLANE_LOAD_15M_WARN", "2.0")),
    )
