from __future__ import annotations

import platform

from fastapi import APIRouter, Header
from fastapi.responses import HTMLResponse

from .config import APP_NAME
from .schemas import HealthResponse, RootResponse, StatusResponse
from .security import require_token
from .system import status_payload

router = APIRouter()


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

    saveBtn.addEventListener("click", () => savePrefs());
    refreshBtn.addEventListener("click", fetchStatus);
    schedule();
  </script>
</body>
</html>
    """
    return HTMLResponse(content=html)
