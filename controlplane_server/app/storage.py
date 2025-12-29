from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterable
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .schemas import EndpointStatus

DB_PATH = Path(os.environ.get("CONTROLPLANE_DB_PATH", ".controlplane.db"))
RETENTION_SEC = os.environ.get("CONTROLPLANE_ENDPOINT_RETENTION_SEC")


@contextmanager
def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    with _conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS endpoints (
                endpoint_id TEXT PRIMARY KEY,
                host TEXT,
                os TEXT,
                python TEXT,
                uptime_sec INTEGER,
                disk_root TEXT,
                cpu_temp_c REAL,
                memory TEXT,
                load_avg TEXT,
                net_io TEXT,
                wifi TEXT,
                battery TEXT,
                warnings TEXT,
                last_seen TEXT
            )
            """
        )
        conn.commit()


def cleanup_retention() -> None:
    if not RETENTION_SEC:
        return
    try:
        retention_seconds = int(RETENTION_SEC)
    except Exception:
        return
    cutoff = datetime.now(UTC) - timedelta(seconds=retention_seconds)
    with _conn() as conn:
        conn.execute(
            "DELETE FROM endpoints WHERE last_seen IS NOT NULL AND last_seen < ?",
            (cutoff.isoformat(),),
        )
        conn.commit()


def save_endpoint(status: EndpointStatus) -> None:
    init_db()
    cleanup_retention()
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO endpoints (
                endpoint_id, host, os, python, uptime_sec, disk_root, cpu_temp_c,
                memory, load_avg, net_io, wifi, battery, warnings, last_seen
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(endpoint_id) DO UPDATE SET
                host=excluded.host,
                os=excluded.os,
                python=excluded.python,
                uptime_sec=excluded.uptime_sec,
                disk_root=excluded.disk_root,
                cpu_temp_c=excluded.cpu_temp_c,
                memory=excluded.memory,
                load_avg=excluded.load_avg,
                net_io=excluded.net_io,
                wifi=excluded.wifi,
                battery=excluded.battery,
                warnings=excluded.warnings,
                last_seen=excluded.last_seen
            """,
            (
                status.endpoint_id,
                status.host,
                status.os,
                status.python,
                status.uptime_sec,
                status.disk_root.model_dump_json(),
                status.cpu_temp_c,
                status.memory.model_dump_json(),
                status.load_avg.as_alias_dict(),
                status.net_io.model_dump_json(),
                status.wifi.model_dump_json() if status.wifi else None,
                status.battery.model_dump_json() if status.battery else None,
                status.warnings,
                status.last_seen,
            ),
        )
        conn.commit()


def _row_to_status(row: tuple) -> EndpointStatus:
    (
        endpoint_id,
        host,
        os_name,
        python,
        uptime_sec,
        disk_root,
        cpu_temp_c,
        memory,
        load_avg,
        net_io,
        wifi,
        battery,
        warnings,
        last_seen,
    ) = row
    return EndpointStatus.model_validate(
        {
            "endpoint_id": endpoint_id,
            "host": host,
            "os": os_name,
            "python": python,
            "uptime_sec": uptime_sec,
            "disk_root": disk_root,
            "cpu_temp_c": cpu_temp_c,
            "memory": memory,
            "load_avg": load_avg,
            "net_io": net_io,
            "wifi": wifi,
            "battery": battery,
            "warnings": warnings,
            "last_seen": last_seen,
        }
    )


def list_endpoints_db() -> Iterable[EndpointStatus]:
    init_db()
    cleanup_retention()
    with _conn() as conn:
        cur = conn.execute(
            "SELECT endpoint_id, host, os, python, uptime_sec, disk_root, cpu_temp_c, "
            "memory, load_avg, net_io, wifi, battery, warnings, last_seen FROM endpoints"
        )
        rows = cur.fetchall()
    return [_row_to_status(row) for row in rows]


def get_endpoint(endpoint_id: str) -> EndpointStatus | None:
    init_db()
    cleanup_retention()
    with _conn() as conn:
        cur = conn.execute(
            "SELECT endpoint_id, host, os, python, uptime_sec, disk_root, cpu_temp_c, "
            "memory, load_avg, net_io, wifi, battery, warnings, last_seen "
            "FROM endpoints WHERE endpoint_id = ?",
            (endpoint_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return _row_to_status(row)


def delete_endpoint(endpoint_id: str) -> None:
    init_db()
    with _conn() as conn:
        conn.execute("DELETE FROM endpoints WHERE endpoint_id = ?", (endpoint_id,))
        conn.commit()
