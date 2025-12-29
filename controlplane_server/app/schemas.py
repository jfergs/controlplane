from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RootResponse(BaseModel):
    name: str
    status: str

    model_config = ConfigDict(
        json_schema_extra={"example": {"name": "ControlPlane", "status": "ok"}}
    )


class HealthResponse(BaseModel):
    ok: bool

    model_config = ConfigDict(json_schema_extra={"example": {"ok": True}})


class DiskInfo(BaseModel):
    total_gb: float | None
    used_gb: float | None
    free_gb: float | None


class MemoryInfo(BaseModel):
    total_gb: float | None
    available_gb: float | None
    percent: float | None


class LoadInfo(BaseModel):
    one_m: float | None = Field(None, alias="1m")
    five_m: float | None = Field(None, alias="5m")
    fifteen_m: float | None = Field(None, alias="15m")

    model_config = ConfigDict(populate_by_name=True)

    def as_alias_dict(self) -> dict[str, float | None]:
        return {"1m": self.one_m, "5m": self.five_m, "15m": self.fifteen_m}


class NetIOInfo(BaseModel):
    bytes_sent: int | None
    bytes_recv: int | None


class WiFiInfo(BaseModel):
    ssid: str | None
    rssi_dbm: int | None
    noise_dbm: int | None


class BatteryInfo(BaseModel):
    percent: float | None
    charging: bool | None


class StatusResponse(BaseModel):
    host: str
    os: str
    python: str
    uptime_sec: int
    disk_root: DiskInfo
    cpu_temp_c: float | None
    memory: MemoryInfo
    load_avg: LoadInfo
    net_io: NetIOInfo
    wifi: WiFiInfo | None = None
    battery: BatteryInfo | None = None
    warnings: list[str]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "host": "host.local",
                "os": "macOS-14.6.1-arm64",
                "python": "3.12.2",
                "uptime_sec": 123456,
                "disk_root": {"total_gb": 512.0, "used_gb": 200.5, "free_gb": 311.5},
                "cpu_temp_c": 52.3,
                "memory": {"total_gb": 16.0, "available_gb": 8.2, "percent": 48.0},
                "load_avg": {"1m": 1.2, "5m": 0.9, "15m": 0.7},
                "net_io": {"bytes_sent": 123456789, "bytes_recv": 987654321},
                "warnings": ["Low disk free space: 0.5 GB < 1.0 GB"],
            }
        }
    )


class EndpointStatus(StatusResponse):
    endpoint_id: str
    last_seen: str


class EndpointList(BaseModel):
    endpoints: list[EndpointStatus]
