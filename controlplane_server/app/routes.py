from __future__ import annotations

# ruff: noqa: E501
import platform
import re
from datetime import UTC, datetime

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import HTMLResponse

from .config import APP_NAME
from .schemas import EndpointList, EndpointStatus, HealthResponse, RootResponse, StatusResponse
from .security import require_token
from .storage import get_endpoint, list_endpoints_db, save_endpoint
from .system import status_payload

router = APIRouter()
_endpoint_store: dict[str, EndpointStatus] = {}


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "endpoint"


@router.get("/", response_model=RootResponse, summary="Service info")
def root():
    return RootResponse(name=APP_NAME, status="ok")


@router.get("/health", response_model=HealthResponse, summary="Liveness check")
def health():
    return HealthResponse(ok=True)


@router.get("/api/status", response_model=StatusResponse, summary="Host status")
def status(authorization: str | None = Header(default=None)):
    require_token(authorization)
    metrics = status_payload()
    return StatusResponse(
        host=platform.node(),
        os=platform.platform(),
        python=platform.python_version(),
        **metrics,
    )


@router.post(
    "/api/push-status", response_model=EndpointStatus, summary="Push remote endpoint status"
)
async def push_status(request: Request, authorization: str | None = Header(default=None)):
    require_token(authorization)
    payload = await request.json()
    if "host" not in payload:
        raise HTTPException(status_code=400, detail="Missing host in payload")
    eid = _slugify(payload.get("host", "endpoint"))
    now = datetime.now(UTC).isoformat()
    data = EndpointStatus(
        endpoint_id=eid,
        last_seen=now,
        **payload,
    )
    save_endpoint(data)
    return data


@router.get("/api/endpoints", response_model=EndpointList, summary="List pushed endpoints")
def list_endpoints(authorization: str | None = Header(default=None)):
    require_token(authorization)
    return EndpointList(endpoints=list(list_endpoints_db()))


@router.get("/api/endpoints/{endpoint_id}", response_model=EndpointStatus, summary="Get endpoint")
def get_endpoint_status(endpoint_id: str, authorization: str | None = Header(default=None)):
    require_token(authorization)
    status = get_endpoint(endpoint_id)
    if not status:
        raise HTTPException(status_code=404, detail="Endpoint not found")
    return status


@router.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
def dashboard() -> HTMLResponse:  # pragma: no cover - HTML UI
    html = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>ControlPlane Dashboard</title>
  <style>
    :root {
      --bg: #0b0f19;
      --panel: #151b2b;
      --panel-alt: #1d2437;
      --text: #e8ecf5;
      --muted: #9aa4bf;
      --accent: #10a37f;
      --danger: #ff5c5c;
      --border: #1f2a44;
      --shadow: 0 18px 60px rgba(0,0,0,0.4);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      padding: 0;
      font-family: "Inter", "SF Pro Display", -apple-system, BlinkMacSystemFont,
        "Segoe UI", sans-serif;
      background: radial-gradient(circle at 20% 20%, rgba(16,163,127,0.08), transparent 35%),
                  radial-gradient(circle at 80% 10%, rgba(113,97,239,0.08), transparent 30%),
                  var(--bg);
      color: var(--text);
      min-height: 100vh;
    }
    header {
      padding: 20px 28px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      position: sticky;
      top: 0;
      background: rgba(11,15,25,0.9);
      backdrop-filter: blur(8px);
      border-bottom: 1px solid var(--border);
      z-index: 10;
    }
    .brand {
      font-weight: 700;
      letter-spacing: 0.5px;
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .pill {
      border: 1px solid var(--border);
      background: var(--panel);
      padding: 10px 12px;
      border-radius: 14px;
      display: flex;
      align-items: center;
      gap: 10px;
      box-shadow: var(--shadow);
    }
    main {
      padding: 24px;
      display: grid;
      gap: 16px;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 14px;
    }
    .card {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 16px;
      box-shadow: var(--shadow);
    }
    .card.alt { background: var(--panel-alt); }
    h2, h3 { margin: 0 0 10px 0; }
    .muted { color: var(--muted); font-size: 14px; }
    .value { font-size: 26px; font-weight: 700; }
    .row { display: flex; justify-content: space-between; align-items: center; margin: 6px 0; }
    .warnings { color: var(--danger); margin: 0; padding-left: 16px; }
    .controls { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
    input, button {
      border-radius: 10px;
      border: 1px solid var(--border);
      background: var(--panel);
      color: var(--text);
      padding: 10px 12px;
      font-size: 14px;
    }
    button {
      background: linear-gradient(135deg, #16b48c, #0e8c6d);
      border: none;
      cursor: pointer;
      font-weight: 600;
      box-shadow: 0 10px 30px rgba(16,163,127,0.3);
    }
    button:disabled { opacity: 0.6; cursor: not-allowed; }
    code { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas,
      "Liberation Mono", "Courier New", monospace; }
  </style>
</head>
<body>
  <header>
    <div class="brand">⚡ ControlPlane Dashboard</div>
    <div class="controls">
      <input id="token" type="password" placeholder="Bearer token" />
      <input id="url" type="text" placeholder="Base URL" value="" />
      <input id="interval" type="number" min="2" value="5" title="Refresh seconds" />
      <button id="save">Save</button>
      <button id="refresh">Refresh</button>
    </div>
  </header>
  <main>
    <div class="grid" id="stats-grid"></div>
    <div class="card alt">
      <h3>Endpoints (pushed)</h3>
      <div id="endpoints" class="muted">Loading…</div>
    </div>
    <div class="card">
      <h3>Onboarding</h3>
      <p class="muted">Generate install scripts for macOS or Windows endpoints. They install dependencies, collect metrics, and POST to this server with the bearer token. Scripts verify TLS by default and back off on errors.</p>
      <div class="controls" style="padding:8px 0;">
        <select id="os-select" style="padding: 10px 12px; background: var(--panel); color: var(--text); border: 1px solid var(--border); border-radius: 10px;">
          <option value="macos">macOS (bash)</option>
          <option value="windows">Windows (PowerShell)</option>
        </select>
        <button id="copy-script">Copy script</button>
      </div>
      <pre id="script" style="white-space: pre-wrap; font-size: 12px; color: var(--muted); background: var(--panel); padding: 12px; border-radius: 10px; border: 1px solid var(--border);"></pre>
    </div>
    <div class="card alt">
      <h3>Warnings</h3>
      <ul class="warnings" id="warnings"></ul>
    </div>
    <div class="card">
      <h3>Raw</h3>
      <pre id="raw" style="white-space: pre-wrap; font-size: 12px; color: var(--muted);"></pre>
    </div>
  </main>
  <script>
    const grid = document.getElementById("stats-grid");
    const warningsList = document.getElementById("warnings");
    const raw = document.getElementById("raw");
    const tokenInput = document.getElementById("token");
    const urlInput = document.getElementById("url");
    const intervalInput = document.getElementById("interval");
    const refreshBtn = document.getElementById("refresh");
    const saveBtn = document.getElementById("save");
    const endpointsDiv = document.getElementById("endpoints");
    const scriptPre = document.getElementById("script");
    const copyBtn = document.getElementById("copy-script");
    const osSelect = document.getElementById("os-select");

    const defaultUrl = window.location.origin;
    urlInput.value = localStorage.getItem("cp_url") || defaultUrl;
    tokenInput.value = localStorage.getItem("cp_token") || "";
    intervalInput.value = localStorage.getItem("cp_interval") || "5";

    let timer = null;

    function savePrefs() {
      localStorage.setItem("cp_token", tokenInput.value);
      localStorage.setItem("cp_url", urlInput.value || defaultUrl);
      localStorage.setItem("cp_interval", intervalInput.value || "5");
      schedule();
    }

    function schedule() {
      if (timer) clearInterval(timer);
      const secs = Math.max(2, parseInt(intervalInput.value || "5", 10));
      timer = setInterval(fetchStatus, secs * 1000);
      fetchStatus();
      fetchEndpoints();
    }

    async function fetchStatus() {
      const token = tokenInput.value.trim();
      const base = (urlInput.value || defaultUrl).replace(/\\/$/, "");
      refreshBtn.disabled = true;
      try {
        const resp = await fetch(base + "/api/status", {
          headers: { Authorization: "Bearer " + token },
        });
        if (!resp.ok) throw new Error("HTTP " + resp.status);
        const data = await resp.json();
        render(data);
      } catch (err) {
        raw.textContent = "Error: " + err;
        grid.innerHTML = "";
      } finally {
        refreshBtn.disabled = false;
      }
    }

    function card(title, value, subtitle = "") {
      return `
        <div class="card">
          <div class="muted">${title}</div>
          <div class="value">${value ?? "—"}</div>
          ${subtitle ? `<div class="muted">${subtitle}</div>` : ""}
        </div>
      `;
    }

    function render(data) {
      raw.textContent = JSON.stringify(data, null, 2);
      const cards = [];
      cards.push(card("Host", data.host, data.os));
      cards.push(card("Python", data.python));
      cards.push(card("Uptime (s)", data.uptime_sec));
      const d = data.disk_root || {};
      cards.push(
        card(
          "Disk /",
          `${d.used_gb ?? "?"} / ${d.total_gb ?? "?"} GB`,
          `Free ${d.free_gb ?? "?"} GB`
        )
      );
      const m = data.memory || {};
      cards.push(card("Memory", `${m.percent ?? "?"}%`, `${m.available_gb ?? "?"} GB free`));
      const l = data.load_avg || {};
      cards.push(
        card("Load avg", `1m ${l["1m"] ?? "?"}`, `5m ${l["5m"] ?? "?"} • 15m ${l["15m"] ?? "?"}`)
      );
      const n = data.net_io || {};
      cards.push(card("Net I/O", `${n.bytes_sent ?? "?"} sent`, `${n.bytes_recv ?? "?"} recv`));
      if (data.cpu_temp_c !== undefined) cards.push(card("CPU Temp (C)", data.cpu_temp_c));
      const wifi = data.wifi || {};
      cards.push(card("Wi-Fi", wifi.ssid || "—", `RSSI ${wifi.rssi_dbm ?? "?"} dBm`));
      const bat = data.battery || {};
      cards.push(
        card(
          "Battery",
          `${bat.percent ?? "?"}%`,
          bat.charging === null ? "" : bat.charging ? "Charging" : "Discharging"
        )
      );
      grid.innerHTML = cards.join("");

      const warnings = data.warnings || [];
      warningsList.innerHTML = warnings.length
        ? warnings.map((w) => `<li>${w}</li>`).join("")
        : "<li class='muted'>None</li>";
    }

    async function fetchEndpoints() {
      const token = tokenInput.value.trim();
      const base = (urlInput.value || defaultUrl).replace(/\\/$/, "");
      try {
        const resp = await fetch(base + "/api/endpoints", {
          headers: { Authorization: "Bearer " + token },
        });
        if (!resp.ok) throw new Error("HTTP " + resp.status);
        const data = await resp.json();
        if (!data.endpoints || data.endpoints.length === 0) {
          endpointsDiv.innerHTML = "No endpoints pushed yet.";
          return;
        }
        endpointsDiv.innerHTML = data.endpoints
          .map(
            (e) =>
              `<div class="row"><span>${e.endpoint_id}</span><span class="muted">${e.last_seen}</span></div>`
          )
          .join("");
      } catch (err) {
        endpointsDiv.innerHTML = "Error loading endpoints: " + err;
      }
    }

    function generateScript() {
      const token = tokenInput.value.trim();
      const base = (urlInput.value || defaultUrl).replace(/\\/$/, "");
      const interval = Math.max(10, parseInt(intervalInput.value || "30", 10));
      const backoff = 10;
      const maxBackoff = 300;
      if (osSelect.value === "macos") {
        return `#!/usr/bin/env bash
set -e
token="${token}"
server="${base}"
interval=${interval}
backoff=${backoff}
max_backoff=${maxBackoff}

python3 -m venv ~/.controlplane-agent
source ~/.controlplane-agent/bin/activate
python -m pip install -U pip
python -m pip install psutil requests

cat > ~/controlplane-agent.py <<'PY'
import json, platform, time, requests, os
import psutil
server=os.environ.get("CP_SERVER")
token=os.environ.get("CP_TOKEN")
def payload():
    load1, load5, load15 = (0,0,0)
    try: load1, load5, load15 = os.getloadavg()
    except Exception: pass
    mem = psutil.virtual_memory()
    return {
        "host": platform.node(),
        "os": platform.platform(),
        "python": platform.python_version(),
        "uptime_sec": int(time.time() - psutil.boot_time()),
        "disk_root": {
            "total_gb": round(psutil.disk_usage('/').total/1024**3,2),
            "used_gb": round(psutil.disk_usage('/').used/1024**3,2),
            "free_gb": round(psutil.disk_usage('/').free/1024**3,2),
        },
        "cpu_temp_c": None,
        "memory": {"total_gb": round(mem.total/1024**3,2), "available_gb": round(mem.available/1024**3,2), "percent": round(mem.percent,2)},
        "load_avg": {"1m": round(load1,2), "5m": round(load5,2), "15m": round(load15,2)},
        "net_io": {"bytes_sent": psutil.net_io_counters().bytes_sent, "bytes_recv": psutil.net_io_counters().bytes_recv},
        "wifi": {"ssid": None, "rssi_dbm": None, "noise_dbm": None},
        "battery": {"percent": None, "charging": None},
        "warnings": [],
    }
def post_loop():
    global backoff
    while True:
        try:
            requests.post(
                f"{server}/api/push-status",
                json=payload(),
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            time.sleep(interval)
            backoff = ${backoff}
        except Exception:
            time.sleep(backoff)
            backoff = min(backoff * 2, ${maxBackoff})

post_loop()
PY

cat > ~/Library/LaunchAgents/com.controlplane.agent.plist <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.controlplane.agent</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>-c</string>
    <string>source ~/.controlplane-agent/bin/activate && CP_SERVER=${server} CP_TOKEN=${token} python ~/controlplane-agent.py</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>/tmp/controlplane-agent.log</string>
  <key>StandardErrorPath</key><string>/tmp/controlplane-agent.err</string>
</dict>
</plist>
PLIST

launchctl unload ~/Library/LaunchAgents/com.controlplane.agent.plist 2>/dev/null || true
launchctl load ~/Library/LaunchAgents/com.controlplane.agent.plist
echo "Agent installed and running."
`;
      }
      return `@echo off
set TOKEN=${token}
set SERVER=${base}
python -m venv %USERPROFILE%\\controlplane-agent
call %USERPROFILE%\\controlplane-agent\\Scripts\\activate
python -m pip install -U pip
python -m pip install psutil requests
echo import json, platform, time, requests, os > %USERPROFILE%\\controlplane-agent.py
echo import psutil >> %USERPROFILE%\\controlplane-agent.py
echo server=os.environ.get('SERVER') >> %USERPROFILE%\\controlplane-agent.py
echo token=os.environ.get('TOKEN') >> %USERPROFILE%\\controlplane-agent.py
echo import os >> %USERPROFILE%\\controlplane-agent.py
echo import psutil >> %USERPROFILE%\\controlplane-agent.py
echo import time >> %USERPROFILE%\\controlplane-agent.py
echo import platform >> %USERPROFILE%\\controlplane-agent.py
echo import requests >> %USERPROFILE%\\controlplane-agent.py
echo def payload(): >> %USERPROFILE%\\controlplane-agent.py
echo ^    load1,load5,load15=(0,0,0) >> %USERPROFILE%\\controlplane-agent.py
echo ^    try: load1,load5,load15=os.getloadavg() >> %USERPROFILE%\\controlplane-agent.py
echo ^    except Exception: pass >> %USERPROFILE%\\controlplane-agent.py
echo ^    mem=psutil.virtual_memory() >> %USERPROFILE%\\controlplane-agent.py
echo ^    return { >> %USERPROFILE%\\controlplane-agent.py
echo ^        "host": platform.node(), >> %USERPROFILE%\\controlplane-agent.py
echo ^        "os": platform.platform(), >> %USERPROFILE%\\controlplane-agent.py
echo ^        "python": platform.python_version(), >> %USERPROFILE%\\controlplane-agent.py
echo ^        "uptime_sec": int(time.time()-psutil.boot_time()), >> %USERPROFILE%\\controlplane-agent.py
echo ^        "disk_root": {"total_gb": round(psutil.disk_usage('\\\\').total/1024**3,2), "used_gb": round(psutil.disk_usage('\\\\').used/1024**3,2), "free_gb": round(psutil.disk_usage('\\\\').free/1024**3,2)}, >> %USERPROFILE%\\controlplane-agent.py
echo ^        "cpu_temp_c": None, >> %USERPROFILE%\\controlplane-agent.py
echo ^        "memory": {"total_gb": round(mem.total/1024**3,2), "available_gb": round(mem.available/1024**3,2), "percent": round(mem.percent,2)}, >> %USERPROFILE%\\controlplane-agent.py
echo ^        "load_avg": {"1m": round(load1,2), "5m": round(load5,2), "15m": round(load15,2)}, >> %USERPROFILE%\\controlplane-agent.py
echo ^        "net_io": {"bytes_sent": psutil.net_io_counters().bytes_sent, "bytes_recv": psutil.net_io_counters().bytes_recv}, >> %USERPROFILE%\\controlplane-agent.py
echo ^        "wifi": {"ssid": None, "rssi_dbm": None, "noise_dbm": None}, >> %USERPROFILE%\\controlplane-agent.py
echo ^        "battery": {"percent": None, "charging": None}, >> %USERPROFILE%\\controlplane-agent.py
echo ^        "warnings": [], >> %USERPROFILE%\\controlplane-agent.py
echo ^    } >> %USERPROFILE%\\controlplane-agent.py
echo backoff=${backoff} >> %USERPROFILE%\\controlplane-agent.py
echo max_backoff=${maxBackoff} >> %USERPROFILE%\\controlplane-agent.py
echo interval=${interval} >> %USERPROFILE%\\controlplane-agent.py
echo def post_loop(): >> %USERPROFILE%\\controlplane-agent.py
echo ^    global backoff >> %USERPROFILE%\\controlplane-agent.py
echo ^    while True: >> %USERPROFILE%\\controlplane-agent.py
echo ^        try: >> %USERPROFILE%\\controlplane-agent.py
echo ^            requests.post(f"{SERVER}/api/push-status", json=payload(), headers={"Authorization": f"Bearer {TOKEN}"}, timeout=10) >> %USERPROFILE%\\controlplane-agent.py
echo ^            time.sleep(interval) >> %USERPROFILE%\\controlplane-agent.py
echo ^            backoff=${backoff} >> %USERPROFILE%\\controlplane-agent.py
echo ^        except Exception: >> %USERPROFILE%\\controlplane-agent.py
echo ^            time.sleep(backoff) >> %USERPROFILE%\\controlplane-agent.py
echo ^            backoff = min(backoff * 2, max_backoff) >> %USERPROFILE%\\controlplane-agent.py
echo post_loop() >> %USERPROFILE%\\controlplane-agent.py

schtasks /Create /TN "ControlPlaneAgent" /TR "cmd /c set SERVER=%SERVER%^^&^& set TOKEN=%TOKEN%^^&^& call %USERPROFILE%\\controlplane-agent\\Scripts\\activate ^^&^^& python %USERPROFILE%\\controlplane-agent.py" /SC ONLOGON /RL HIGHEST /F
schtasks /Run /TN "ControlPlaneAgent"
echo Agent installed and scheduled.
`;
    }

    function refreshScript() {
      scriptPre.textContent = generateScript();
    }

    copyBtn.addEventListener("click", async () => {
      await navigator.clipboard.writeText(scriptPre.textContent);
      copyBtn.textContent = "Copied!";
      setTimeout(() => (copyBtn.textContent = "Copy script"), 1200);
    });

    osSelect.addEventListener("change", refreshScript);
    tokenInput.addEventListener("input", refreshScript);
    urlInput.addEventListener("input", refreshScript);

    saveBtn.addEventListener("click", () => savePrefs());
    refreshBtn.addEventListener("click", fetchStatus);
    refreshScript();
    schedule();
  </script>
</body>
</html>
    """
    return HTMLResponse(content=html)
