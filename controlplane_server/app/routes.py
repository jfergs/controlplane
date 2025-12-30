from __future__ import annotations

import hashlib
import hmac
import json
import os

# ruff: noqa: E501
import platform
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import APIRouter, Header, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from .config import APP_NAME
from .schemas import (
    EndpointHealth,
    EndpointList,
    EndpointStatus,
    HealthResponse,
    RootResponse,
    StatusResponse,
)
from .security import require_token
from .storage import delete_endpoint, get_endpoint, list_endpoints_db, save_endpoint
from .system import status_payload

router = APIRouter()
_endpoint_store: dict[str, EndpointStatus] = {}
_creds_file = Path(".controlplane_login.json")
_session_cookie = "cp_auth"


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


@router.get(
    "/api/endpoints/health", response_model=EndpointHealth, summary="Endpoint health summary"
)
def endpoint_health(authorization: str | None = Header(default=None)):
    require_token(authorization)
    endpoints = list(list_endpoints_db())
    total = len(endpoints)
    stale = 0
    for e in endpoints:
        try:
            last = datetime.fromisoformat(e.last_seen)
            diff = (datetime.now(UTC) - last).total_seconds()
            if diff > 300:
                stale += 1
        except Exception:
            stale += 1
    active = max(total - stale, 0)
    return EndpointHealth(active=active, stale=stale, total=total)


@router.delete("/api/endpoints/{endpoint_id}", status_code=204, summary="Delete endpoint")
def delete_endpoint_status(endpoint_id: str, authorization: str | None = Header(default=None)):
    require_token(authorization)
    existing = get_endpoint(endpoint_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Endpoint not found")
    delete_endpoint(endpoint_id)
    return Response(status_code=204)


@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
def login_get(request: Request) -> HTMLResponse:  # pragma: no cover
    if _is_authed(request):
        return RedirectResponse(url="/dashboard", status_code=302)
    needs_setup = _load_creds() is None
    html = f"""
<!DOCTYPE html>
<html>
<head><title>ControlPlane Login</title></head>
<body style="font-family: sans-serif; background: #0b0f19; color: #e8ecf5; display: flex; align-items: center; justify-content: center; min-height: 100vh;">
  <form method="post" action="/login" style="background: #151b2b; padding: 20px; border-radius: 12px; border: 1px solid #1f2a44; min-width: 280px;">
    <h3>{"Setup" if needs_setup else "Login"}</h3>
    <label>Username<br><input name="username" required style="width: 100%; padding: 8px; border-radius: 8px; border: 1px solid #1f2a44; background: #0b0f19; color: #e8ecf5;"></label><br><br>
    <label>Password<br><input type="password" name="password" required style="width: 100%; padding: 8px; border-radius: 8px; border: 1px solid #1f2a44; background: #0b0f19; color: #e8ecf5;"></label><br><br>
    <button type="submit" style="width: 100%; padding: 10px; border: none; border-radius: 10px; background: linear-gradient(135deg, #10a37f, #06b6d4); color: white; font-weight: 700; cursor: pointer;">{"Create account" if needs_setup else "Login"}</button>
  </form>
</body>
</html>
    """
    return HTMLResponse(content=html)


@router.post("/login", include_in_schema=False)
async def login_post(request: Request):
    body = (await request.body()).decode()
    data = parse_qs(body)
    username = (data.get("username") or [""])[0]
    password = (data.get("password") or [""])[0]
    if not username or not password:
        return HTMLResponse(content="Invalid credentials", status_code=400)
    creds = _load_creds()
    if creds is None:
        _save_creds(username, password)
    elif not _check_password(username, password):
        return HTMLResponse(content="Invalid credentials", status_code=401)
    resp = RedirectResponse(url="/dashboard", status_code=302)
    resp.set_cookie(_session_cookie, _make_session_cookie(), httponly=True, samesite="lax")
    return resp


@router.get("/logout", include_in_schema=False)
def logout():
    resp = RedirectResponse(url="/login", status_code=302)
    resp.delete_cookie(_session_cookie)
    return resp


@router.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
def dashboard(request: Request) -> HTMLResponse:  # pragma: no cover - HTML UI
    if not _is_authed(request):
        return RedirectResponse(url="/login", status_code=302)
    token_js = json.dumps(os.environ.get("CONTROLPLANE_TOKEN", ""))
    html = (
        """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>ControlPlane Dashboard</title>
  <link rel="icon" type="image/png" href="/static/aircon.png" />
  <style>
    :root {
      --bg: #0b0f19;
      --panel: #151b2b;
      --panel-alt: #1d2437;
      --text: #e8ecf5;
      --muted: #9aa4bf;
      --accent: #10a37f;
      --accent-2: #06b6d4;
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
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 12px;
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
    input, button, select {
      border-radius: 10px;
      border: 1px solid var(--border);
      background: var(--panel);
      color: var(--text);
      padding: 10px 12px;
      font-size: 14px;
    }
    .endpoint-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 320px));
      gap: 12px;
      justify-content: center;
    }
    .endpoint-card {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 10px;
      display: flex;
      flex-direction: column;
      gap: 6px;
      box-shadow: 0 6px 14px rgba(0,0,0,0.14);
      transition: transform 0.15s ease, box-shadow 0.15s ease, border-color 0.15s ease;
      aspect-ratio: 3 / 4;
      overflow: hidden;
      max-width: 320px;
      width: 100%;
    }
    .endpoint-card.stale { border-color: #f97316; }
    .endpoint-card h4 { margin: 0; font-size: 16px; }
    .endpoint-card.expanded {
      transform: scale(1.02);
      box-shadow: 0 12px 26px rgba(0,0,0,0.2);
      border-color: var(--accent);
      aspect-ratio: auto;
      overflow: visible;
    }
    .endpoint-meta {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      color: var(--muted);
      font-size: 12px;
    }
    .endpoint-actions {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }
    .endpoint-actions button {
      padding: 8px 10px;
      border-radius: 8px;
      border: 1px solid var(--border);
      background: var(--panel-alt);
      color: var(--text);
      cursor: pointer;
    }
    .endpoint-actions button.primary {
      border-color: var(--accent);
      color: var(--accent);
    }
    .endpoint-detail {
      border-top: 1px solid var(--border);
      padding-top: 8px;
      margin-top: 4px;
      display: none;
    }
    .endpoint-detail pre {
      white-space: pre-wrap;
      font-size: 12px;
      color: var(--muted);
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 10px;
      margin: 0;
    }
    .endpoint-detail.show { display: block; }
    .os-pill {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 8px;
      background: var(--panel-alt);
      border: 1px solid var(--border);
      border-radius: 10px;
      font-size: 12px;
      color: var(--muted);
    }
    .os-pill svg {
      width: 16px;
      height: 16px;
      stroke: currentColor;
    }
    .device-pill {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 8px;
      background: var(--panel);
      border: 1px dashed var(--border);
      border-radius: 10px;
      font-size: 12px;
      color: var(--muted);
    }
    .device-pill svg {
      width: 16px;
      height: 16px;
      stroke: currentColor;
    }
    .section-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
    }
    .awaken-btn {
      position: fixed;
      bottom: 18px;
      right: 18px;
      padding: 10px 12px;
      border-radius: 12px;
      background: linear-gradient(135deg, #10a37f, #06b6d4);
      color: #fff;
      border: none;
      cursor: pointer;
      box-shadow: 0 12px 30px rgba(0,0,0,0.25);
    }
    .awaken-btn:disabled {
      opacity: 0.65;
      cursor: default;
    }
    .panel-menu { position: relative; }
    .panel-menu button { min-width: 90px; }
    .panel-dropdown {
      position: absolute;
      top: 110%;
      right: 0;
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 8px;
      box-shadow: var(--shadow);
      min-width: 160px;
    }
    .panel-item { margin: 6px 0; }
    button {
      background: linear-gradient(135deg, var(--accent), var(--accent-2));
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
    <div class="brand">
      <img id="header-icon" src="/static/aircon.png" alt="ControlPlane" style="width:56px;height:56px;border-radius:10px;" />
      <span>ControlPlane Dashboard</span>
    </div>
    <div class="controls">
      <label style="display:flex;align-items:center;gap:6px;font-size:13px;" title="Hide onboarding/scripts">
        <input id="lockdown-toggle" type="checkbox" />
        Lockdown
      </label>
      <div class="pill" id="health-pill">Endpoints: —</div>
      <select id="theme-select" style="min-width: 150px;">
        <option value="default">Default</option>
        <option value="midnight">Midnight Teal</option>
        <option value="graphite">Graphite Neon</option>
        <option value="obsidian">Obsidian Orange</option>
        <option value="emerald">Emerald Slate</option>
        <option value="indigo">Indigo Rose</option>
      </select>
      <button id="refresh">Refresh</button>
      <div class="panel-menu">
        <button id="panels-toggle">Panels</button>
        <div id="panels-dropdown" class="panel-dropdown" hidden>
          <div class="panel-item"><label><input type="checkbox" id="toggle-onboarding" /> Onboarding</label></div>
          <div class="panel-item"><label><input type="checkbox" id="toggle-warnings" /> Warnings</label></div>
          <div class="panel-item"><label><input type="checkbox" id="toggle-grid" /> THE GRID</label></div>
        </div>
      </div>
    </div>
  </header>
  <main>
    <div class="card alt">
      <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;">
        <h3 style="margin:0;">Devices</h3>
        <div class="controls" style="padding:6px 0; gap:6px;">
          <button id="expand-all">Expand all</button>
          <input id="filter-search" type="text" placeholder="Search name/OS/warnings" style="min-width: 180px;" />
          <select id="filter-status">
            <option value="all">All</option>
            <option value="active">Active</option>
            <option value="stale">Stale</option>
          </select>
          <select id="filter-os">
            <option value="all">All OS</option>
            <option value="windows">Windows</option>
            <option value="mac">macOS</option>
            <option value="linux">Linux</option>
            <option value="other">Other</option>
          </select>
          <select id="filter-kind">
            <option value="all">All types</option>
            <option value="desktop">Desktop</option>
            <option value="laptop">Laptop</option>
            <option value="server">Server</option>
          </select>
          <button id="filter-reset">Reset filters</button>
        </div>
      </div>
      <div id="devices" class="endpoint-grid">Loading…</div>
    </div>
    <div class="card" id="summary-card">
      <div class="section-header">
        <h3 style="margin:0;">Summary</h3>
      </div>
      <div class="grid" id="summary-grid"></div>
    </div>
    <div class="card" id="onboarding-card" hidden>
      <div class="section-header">
        <h3 style="margin:0;">Onboarding</h3>
        <button id="onboarding-toggle">Show</button>
      </div>
      <div id="onboarding-content" hidden>
        <p class="muted">Generate install scripts for macOS or Windows endpoints. They install dependencies, collect metrics, and POST to this server with the bearer token. Scripts verify TLS by default and back off on errors.</p>
        <div class="controls" style="padding:8px 0; gap:6px;">
          <input id="token" type="password" placeholder="Bearer token" />
          <input id="url" type="text" placeholder="Base URL" value="" />
          <input id="interval" type="number" min="2" value="5" title="Refresh seconds" />
          <button id="rotate-token">Generate token</button>
          <button id="save">Save</button>
        </div>
        <div class="muted" style="font-size:12px;">After generating a new token, update <code>CONTROLPLANE_TOKEN</code> in your server env and restart the container.</div>
        <div class="controls" style="padding:8px 0; gap:6px;">
          <select id="os-select" style="padding: 10px 12px; background: var(--panel); color: var(--text); border: 1px solid var(--border); border-radius: 10px;">
            <option value="macos">macOS (bash)</option>
            <option value="windows">Windows (PowerShell)</option>
          </select>
          <button id="script-toggle">Show</button>
          <button id="copy-script">Copy script</button>
          <button id="copy-uninstall">Copy uninstall</button>
        </div>
        <pre id="script" hidden style="white-space: pre-wrap; font-size: 12px; color: var(--muted); background: var(--panel); padding: 12px; border-radius: 10px; border: 1px solid var(--border);"></pre>
      </div>
    </div>
    <div class="card alt" id="warnings-card" hidden>
      <div class="section-header">
        <h3 style="margin:0;">Warnings</h3>
        <button id="warnings-toggle">Show</button>
      </div>
      <ul class="warnings" id="warnings" hidden></ul>
    </div>
    <div class="card" id="grid-card" hidden>
      <div class="section-header">
        <h3>THE GRID</h3>
        <button id="raw-toggle">Show</button>
      </div>
      <pre id="raw" hidden style="white-space: pre-wrap; font-size: 12px; color: var(--muted);"></pre>
    </div>
  </main>
  <button id="awaken-btn" class="awaken-btn">Awaken</button>
  <script>
    const devicesGrid = document.getElementById("devices");
    const warningsList = document.getElementById("warnings");
    const raw = document.getElementById("raw");
    const tokenInput = document.getElementById("token");
    const urlInput = document.getElementById("url");
    const intervalInput = document.getElementById("interval");
    const refreshBtn = document.getElementById("refresh");
    const saveBtn = document.getElementById("save");
    const endpointsDiv = devicesGrid; // alias for clarity
    const scriptPre = document.getElementById("script");
    const copyBtn = document.getElementById("copy-script");
    const copyUninstallBtn = document.getElementById("copy-uninstall");
    const osSelect = document.getElementById("os-select");
    const themeSelect = document.getElementById("theme-select");
    const onboardingToggle = document.getElementById("onboarding-toggle");
    const onboardingContent = document.getElementById("onboarding-content");
    const scriptToggleBtn = document.getElementById("script-toggle");
    const rawToggleBtn = document.getElementById("raw-toggle");
    const awakenBtn = document.getElementById("awaken-btn");
    const headerIcon = document.getElementById("header-icon");
    const faviconLink = document.querySelector("link[rel='icon']");
    const warningsToggleBtn = document.getElementById("warnings-toggle");
    const expandAllBtn = document.getElementById("expand-all");
    const filterStatus = document.getElementById("filter-status");
    const filterOs = document.getElementById("filter-os");
    const filterKind = document.getElementById("filter-kind");
    const filterSearch = document.getElementById("filter-search");
    const filterReset = document.getElementById("filter-reset");
    const summaryGrid = document.getElementById("summary-grid");
    const rotateTokenBtn = document.getElementById("rotate-token");
    const onboardingCard = document.getElementById("onboarding-card");
    const warningsCard = document.getElementById("warnings-card");
    const gridCard = document.getElementById("grid-card");
    const panelsToggleBtn = document.getElementById("panels-toggle");
    const panelsDropdown = document.getElementById("panels-dropdown");
    const toggleOnboarding = document.getElementById("toggle-onboarding");
    const toggleWarnings = document.getElementById("toggle-warnings");
    const toggleGrid = document.getElementById("toggle-grid");
    const healthPill = document.getElementById("health-pill");
    const lockdownToggle = document.getElementById("lockdown-toggle");

    const defaultUrl = window.location.origin;
    const defaultToken = """
        + token_js
        + """;
    urlInput.value = localStorage.getItem("cp_url") || defaultUrl;
    tokenInput.value = localStorage.getItem("cp_token") || defaultToken;
    intervalInput.value = localStorage.getItem("cp_interval") || "5";
    themeSelect.value = localStorage.getItem("cp_theme") || "graphite";

    let timer = null;
    let hostStatus = null;
    let endpointsCache = [];
    let scriptVisible = false;
    let rawVisible = false;
    let expandedIds = new Set();
    let onboardingVisible = false;
    let expandAllActive = false;
    let lockdown = localStorage.getItem("cp_lockdown") === "1";
    let lastRefresh = null;
    let lastError = null;
    // initialize visibility from panel toggles
    onboardingVisible = toggleOnboarding.checked;
    onboardingCard.hidden = !onboardingVisible;
    onboardingContent.hidden = !onboardingVisible;
    onboardingToggle.textContent = onboardingVisible ? "Hide" : "Show";
    warningsCard.hidden = !toggleWarnings.checked;
    warningsList.hidden = !toggleWarnings.checked;
    warningsToggleBtn.textContent = toggleWarnings.checked ? "Hide" : "Show";
    rawVisible = toggleGrid.checked;
    gridCard.hidden = !rawVisible;
    raw.hidden = !rawVisible;
    rawToggleBtn.textContent = rawVisible ? "Hide" : "Show";
    lockdownToggle.checked = lockdown;
    applyLockdown();

    function savePrefs() {
      localStorage.setItem("cp_token", tokenInput.value);
      localStorage.setItem("cp_url", urlInput.value || defaultUrl);
      localStorage.setItem("cp_interval", intervalInput.value || "5");
      localStorage.setItem("cp_theme", themeSelect.value || "graphite");
      localStorage.setItem("cp_lockdown", lockdown ? "1" : "0");
    schedule();
  }

    function generateToken() {
      if (window.crypto && window.crypto.getRandomValues) {
        const arr = new Uint8Array(24);
        window.crypto.getRandomValues(arr);
        return Array.from(arr, (b) => b.toString(16).padStart(2, "0")).join("");
      }
      // fallback
      return Math.random().toString(36).slice(2) + Math.random().toString(36).slice(2);
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
        hostStatus = data;
        render(data);
        renderDevices();
        lastRefresh = Date.now();
        lastError = null;
        updateHealthPill();
      } catch (err) {
        raw.textContent = "Error: " + err;
        lastError = err?.message || String(err);
        hostStatus = null;
        devicesGrid.innerHTML = "Error loading host: " + err;
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
        endpointsCache = data.endpoints || [];
        renderDevices();
      } catch (err) {
        endpointsDiv.innerHTML = "Error loading endpoints: " + err;
      }
    }

    function timeAgo(iso) {
      try {
        const then = new Date(iso);
        const diff = (Date.now() - then.getTime()) / 1000;
        if (diff < 60) return `${Math.round(diff)}s ago`;
        if (diff < 3600) return `${Math.round(diff/60)}m ago`;
        if (diff < 86400) return `${Math.round(diff/3600)}h ago`;
        return `${Math.round(diff/86400)}d ago`;
      } catch {
        return iso;
      }
    }

    function isStale(iso) {
      try {
        const then = new Date(iso);
        const diff = (Date.now() - then.getTime()) / 1000;
        return diff > 300;
      } catch {
        return false;
      }
    }

    function formatDuration(seconds) {
      if (seconds == null) return "—";
      const sec = Math.max(0, Math.floor(seconds));
      const days = Math.floor(sec / 86400);
      const hours = Math.floor((sec % 86400) / 3600);
      const mins = Math.floor((sec % 3600) / 60);
      if (days) return `${days}d ${hours}h`;
      if (hours) return `${hours}h ${mins}m`;
      return `${mins}m`;
    }

    function escapeHtml(str) {
      return str
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
    }

    function renderDevices() {
      const items = [];
      if (hostStatus) {
        const hostData = {
          ...hostStatus,
          endpoint_id: "local-host",
          os: hostStatus.os,
          last_seen: new Date().toISOString(),
          uptime_sec: hostStatus.uptime_sec,
        };
        items.push(hostData);
      }
      const sorted = [...endpointsCache].sort((a, b) =>
        (b.last_seen || "").localeCompare(a.last_seen || "")
      );
      sorted.forEach((e) => items.push(e));
      const filtered = items.filter(matchesFilters);
      const rendered = filtered.map((e) => renderTile(e, e.endpoint_id === "local-host"));
      if (!rendered.length) {
        devicesGrid.innerHTML = "No devices match the filters.";
      } else {
        devicesGrid.innerHTML = rendered.join("");
      }
      updateHealthPill();
      renderSummary();
    }

    function renderTile(e, isHost) {
      const age = isHost ? "just now" : timeAgo(e.last_seen);
      const stale = isHost ? false : isStale(e.last_seen);
      const uptime = formatDuration(e.uptime_sec);
      const detail = renderDetail(e);
      const osIcon = iconForOs(e.os);
      const deviceIcon = iconForDevice(deviceKind(e));
      const label = isHost ? "Host" : "Endpoint";
      const expanded = expandedIds.has(e.endpoint_id);
      const deleteBtn = isHost
        ? ""
        : `<button data-action="delete" data-id="${e.endpoint_id}">Delete</button>`;
      return `<div class="endpoint-card ${stale ? "stale" : ""} ${expanded ? "expanded" : ""}" data-id="${e.endpoint_id}">
        <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;">
          <div>
            <div style="display:flex;align-items:center;gap:6px;">
              <div class="device-pill">${deviceIcon}<span>${deviceKind(e)}</span></div>
              <h4 style="margin:0;">${e.endpoint_id}</h4>
            </div>
            <div class="os-pill">${osIcon}<span>${e.os || "unknown"}</span></div>
          </div>
          <div class="muted" style="font-size:12px;">${label}</div>
        </div>
        <div class="endpoint-meta">
          <span>Last seen ${age}${stale ? " • stale" : ""}</span>
          <span>Uptime: ${uptime}</span>
        </div>
        <div class="endpoint-actions">
          <button class="primary" data-action="toggle" data-id="${e.endpoint_id}">${expanded ? "Hide" : "Show"}</button>
          ${deleteBtn}
        </div>
        <div class="endpoint-detail ${expanded ? "show" : ""}">${detail}</div>
      </div>`;
    }

    function renderDetail(e) {
      const items = [];
      items.push(card("Host", e.host || e.endpoint_id, e.os || ""));
      items.push(card("Python", e.python || "—"));
      items.push(card("Uptime", formatDuration(e.uptime_sec)));
      if (e.disk_root) {
        items.push(card("Disk /", `${e.disk_root.used_gb ?? "?"} / ${e.disk_root.total_gb ?? "?"} GB`, `Free ${e.disk_root.free_gb ?? "?"} GB`));
      }
      if (e.memory) {
        items.push(card("Memory", `${e.memory.percent ?? "?"}%`, `${e.memory.available_gb ?? "?"} GB free`));
      }
      if (e.load_avg) {
        items.push(card("Load avg", `1m ${e.load_avg["1m"] ?? "?"}`, `5m ${e.load_avg["5m"] ?? "?"} • 15m ${e.load_avg["15m"] ?? "?"}`));
      }
      if (e.net_io) {
        items.push(card("Net I/O", `${e.net_io.bytes_sent ?? "?"} sent`, `${e.net_io.bytes_recv ?? "?"} recv`));
      }
      if (e.wifi) {
        items.push(card("Wi-Fi", e.wifi.ssid || "—", `RSSI ${e.wifi.rssi_dbm ?? "?"} dBm`));
      }
      if (e.battery) {
        items.push(card("Battery", `${e.battery.percent ?? "?"}%`, e.battery.charging === null ? "" : e.battery.charging ? "Charging" : "Discharging"));
      }
      const warnings = e.warnings && e.warnings.length
        ? `<ul class="warnings">${e.warnings.map((w) => `<li>${escapeHtml(String(w))}</li>`).join("")}</ul>`
        : "<div class='muted'>No warnings</div>";
      const raw = `<pre>${escapeHtml(JSON.stringify(e, null, 2))}</pre>`;
      return `<div class="grid">${items.join("")}</div>${warnings}${raw}`;
    }

    async function deleteEndpoint(endpointId) {
      const token = tokenInput.value.trim();
      const base = (urlInput.value || defaultUrl).replace(/\\/$/, "");
      if (!confirm(`Delete endpoint ${endpointId}?`)) return;
      try {
        const resp = await fetch(base + "/api/endpoints/" + endpointId, {
          method: "DELETE",
          headers: { Authorization: "Bearer " + token },
        });
        if (!resp.ok && resp.status !== 204) throw new Error("HTTP " + resp.status);
        fetchEndpoints();
      } catch (err) {
        alert("Failed to delete: " + err);
      }
    }

    function summarizeHealth(endpoints) {
      let active = 0;
      let stale = 0;
      endpoints.forEach((e) => {
        if (isStale(e.last_seen)) stale += 1;
        else active += 1;
      });
      return { active, stale };
    }

    function matchesFilters(e) {
      const statusFilter = filterStatus.value;
      const osFilter = filterOs.value;
      const kindFilter = filterKind.value;
      const stale = isStale(e.last_seen);
      const search = (filterSearch.value || "").toLowerCase().trim();
      if (statusFilter === "active" && stale) return false;
      if (statusFilter === "stale" && !stale) return false;
      const lowerOs = (e.os || "").toLowerCase();
      if (osFilter === "windows" && !lowerOs.includes("windows")) return false;
      if (osFilter === "mac" && !(lowerOs.includes("darwin") || lowerOs.includes("mac"))) return false;
      if (osFilter === "linux" && !lowerOs.includes("linux")) return false;
      if (osFilter === "other" && (lowerOs.includes("windows") || lowerOs.includes("darwin") || lowerOs.includes("mac") || lowerOs.includes("linux"))) return false;
      const dk = deviceKind(e).toLowerCase();
      if (kindFilter !== "all" && dk !== kindFilter) return false;
      if (search) {
        const haystack = [
          e.endpoint_id || "",
          e.host || "",
          e.os || "",
          (e.warnings || []).join(" "),
        ]
          .join(" ")
          .toLowerCase();
        if (!haystack.includes(search)) return false;
      }
      return true;
    }

    function deviceKind(e) {
      const host = (e.endpoint_id || e.host || "").toLowerCase();
      const os = (e.os || "").toLowerCase();
      if (host.match(/(laptop|notebook|macbook|mbp|air)/)) return "Laptop";
      if (host.match(/(srv|server|prd|prod|vm|node|rack)/)) return "Server";
      if (os.includes("windows server")) return "Server";
      return "Desktop";
    }

    function iconForDevice(kind) {
      const k = (kind || "").toLowerCase();
      if (k === "laptop") {
        return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke-width="1.5"><path d="M4 6h16v8H4z" stroke="currentColor"/><path d="M2 17h20" stroke="currentColor"/><path d="M8 19h8" stroke="currentColor"/></svg>';
      }
      if (k === "server") {
        return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke-width="1.5"><rect x="4" y="4" width="16" height="6" rx="1.2" stroke="currentColor"/><rect x="4" y="12" width="16" height="6" rx="1.2" stroke="currentColor"/><circle cx="8" cy="7" r=".8" fill="currentColor"/><circle cx="8" cy="15" r=".8" fill="currentColor"/></svg>';
      }
      // desktop default
      return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke-width="1.5"><rect x="4" y="5" width="16" height="12" rx="1.2" stroke="currentColor"/><path d="M9 19h6" stroke="currentColor"/><path d="M10 17h4" stroke="currentColor"/></svg>';
    }

    function iconForOs(osName) {
      const lower = (osName || "").toLowerCase();
      if (lower.includes("windows")) return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke-width="1.5"><path d="M4 5.5l7-1.5v8h-7zm8 0l8-1.5v9h-8zm-8 9.5h7v7l-7-1.5zm8 0h8v7l-8-1.5z" stroke="currentColor"/></svg>';
      if (lower.includes("darwin") || lower.includes("mac") || lower.includes("os x")) return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke-width="1.5"><path d="M17 3c-.6.8-1.2 1.3-2 1.6-.3-.8-.8-1.5-1.5-2 .8-.3 1.6-.6 2.5-.6 1 0 1.8.3 2.5.9-.5.9-1.1 1.4-1.5 1.6zM12.7 6c1.2 0 2.2.4 3 .4.6 0 1.6-.4 2.8-.4-.7 1.8-.3 4.5-.3 4.5s-1.6.2-2.6-1.2c-.9-1.2-.9-2.3-2.8-2.3s-2 1.2-3.2 2.4c-1.2 1.2-2.3 1-2.3 1 .2-1.8 1-3.4 2.2-4.5.8-.7 1.7-1.1 2.2-1.1zm-3 6.8c1.1.9 2.1.8 3.5.3 1.4-.5 2.1-.5 3.1 0 1.2.6 2.1.6 3.1 0 0 0-.3 1.2-1.1 2.3-.8 1.2-2 2.1-3.1 2.1-1 0-1.7-.7-2.9-.7-1.2 0-1.9.7-3 .7-1 0-2.1-.8-3-2.1-.9-1.2-1.4-2.9-1.4-2.9s1.6.3 2.8.3z" stroke="currentColor" stroke-linejoin="round"/></svg>';
      if (lower.includes("linux")) return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke-width="1.5"><path d="M12 3c-1.8 0-3 1.5-3 3.3v6.9c0 2.2-.4 3.8-1.5 5.5-.2.3-.1.8.2 1 .3.2.8.1 1-.2 1.1-1.7 1.8-3.5 1.8-6.3h1v6.3c0 .4.3.8.7.8s.8-.4.8-.8v-6.3h1c0 2.8.7 4.7 1.8 6.4.2.3.6.4 1 .2.3-.2.4-.6.2-1-1.1-1.7-1.5-3.3-1.5-5.6V6.3C15 4.5 13.8 3 12 3z" stroke="currentColor"/><circle cx="10" cy="6.5" r=".7" fill="currentColor"/><circle cx="14" cy="6.5" r=".7" fill="currentColor"/></svg>';
      return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke-width="1.5"><path d="M4 6h16v12H4z" stroke="currentColor"/><path d="M8 10h8" stroke="currentColor"/><path d="M8 14h5" stroke="currentColor"/></svg>';
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

mkdir -p ~/.controlplane-agent
cat > ~/.controlplane-agent/config.json <<'JSON'
{
  "server": "${base}",
  "token": "${token}",
  "interval_sec": ${interval},
  "backoff_sec": ${backoff},
  "max_backoff_sec": ${maxBackoff}
}
JSON

cat > ~/controlplane-agent.py <<'PY'
import json, platform, time, requests, os
import psutil
CONFIG_PATH=os.path.expanduser("~/.controlplane-agent/config.json")

def load_config():
    cfg = {
        "server": os.environ.get("CP_SERVER"),
        "token": os.environ.get("CP_TOKEN"),
        "interval_sec": ${interval},
        "backoff_sec": ${backoff},
        "max_backoff_sec": ${maxBackoff},
    }
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            loaded = json.load(fh)
            cfg.update({k: v for k, v in loaded.items() if v is not None})
    except Exception:
        pass
    return cfg

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
    while True:
        cfg = load_config()
        server = cfg.get("server")
        token = cfg.get("token")
        interval_sec = cfg.get("interval_sec", ${interval})
        backoff_sec = cfg.get("backoff_sec", ${backoff})
        max_bk = cfg.get("max_backoff_sec", ${maxBackoff})
        if not server or not token:
            time.sleep(backoff_sec)
            continue
        try:
            requests.post(
                f"{server}/api/push-status",
                json=payload(),
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            time.sleep(interval_sec)
        except Exception:
            time.sleep(backoff_sec)
            backoff_sec = min(backoff_sec * 2, max_bk)

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
    <string>source ~/.controlplane-agent/bin/activate && python ~/controlplane-agent.py</string>
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
echo { > %USERPROFILE%\\controlplane-agent\\config.json
echo   "server": "%SERVER%", >> %USERPROFILE%\\controlplane-agent\\config.json
echo   "token": "%TOKEN%", >> %USERPROFILE%\\controlplane-agent\\config.json
echo   "interval_sec": ${interval}, >> %USERPROFILE%\\controlplane-agent\\config.json
echo   "backoff_sec": ${backoff}, >> %USERPROFILE%\\controlplane-agent\\config.json
echo   "max_backoff_sec": ${maxBackoff} >> %USERPROFILE%\\controlplane-agent\\config.json
echo } >> %USERPROFILE%\\controlplane-agent\\config.json
echo import json, platform, time, requests, os > %USERPROFILE%\\controlplane-agent.py
echo import psutil >> %USERPROFILE%\\controlplane-agent.py
echo CONFIG_PATH=os.path.expanduser("%USERPROFILE%\\controlplane-agent\\config.json") >> %USERPROFILE%\\controlplane-agent.py
echo def load_config(): >> %USERPROFILE%\\controlplane-agent.py
echo ^    cfg={"server": os.environ.get('SERVER'), "token": os.environ.get('TOKEN'), "interval_sec": ${interval}, "backoff_sec": ${backoff}, "max_backoff_sec": ${maxBackoff}} >> %USERPROFILE%\\controlplane-agent.py
echo ^    try: >> %USERPROFILE%\\controlplane-agent.py
echo ^        with open(CONFIG_PATH, "r", encoding="utf-8") as fh: >> %USERPROFILE%\\controlplane-agent.py
echo ^            import json >> %USERPROFILE%\\controlplane-agent.py
echo ^            cfg.update(json.load(fh)) >> %USERPROFILE%\\controlplane-agent.py
echo ^    except Exception: >> %USERPROFILE%\\controlplane-agent.py
echo ^        pass >> %USERPROFILE%\\controlplane-agent.py
echo ^    return cfg >> %USERPROFILE%\\controlplane-agent.py
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
echo def post_loop(): >> %USERPROFILE%\\controlplane-agent.py
echo ^    while True: >> %USERPROFILE%\\controlplane-agent.py
echo ^        cfg=load_config() >> %USERPROFILE%\\controlplane-agent.py
echo ^        server=cfg.get("server") >> %USERPROFILE%\\controlplane-agent.py
echo ^        token=cfg.get("token") >> %USERPROFILE%\\controlplane-agent.py
echo ^        interval_sec=cfg.get("interval_sec", ${interval}) >> %USERPROFILE%\\controlplane-agent.py
echo ^        backoff_sec=cfg.get("backoff_sec", ${backoff}) >> %USERPROFILE%\\controlplane-agent.py
echo ^        max_bk=cfg.get("max_backoff_sec", ${maxBackoff}) >> %USERPROFILE%\\controlplane-agent.py
echo ^        if not server or not token: >> %USERPROFILE%\\controlplane-agent.py
echo ^            time.sleep(backoff_sec) >> %USERPROFILE%\\controlplane-agent.py
echo ^            continue >> %USERPROFILE%\\controlplane-agent.py
echo ^        try: >> %USERPROFILE%\\controlplane-agent.py
echo ^            requests.post(f"{SERVER}/api/push-status", json=payload(), headers={"Authorization": f"Bearer {TOKEN}"}, timeout=10) >> %USERPROFILE%\\controlplane-agent.py
echo ^            time.sleep(interval_sec) >> %USERPROFILE%\\controlplane-agent.py
echo ^        except Exception: >> %USERPROFILE%\\controlplane-agent.py
echo ^            time.sleep(backoff_sec) >> %USERPROFILE%\\controlplane-agent.py
echo ^            backoff_sec=min(backoff_sec*2, max_bk) >> %USERPROFILE%\\controlplane-agent.py
echo post_loop() >> %USERPROFILE%\\controlplane-agent.py

schtasks /Create /TN "ControlPlaneAgent" /TR "cmd /c call %USERPROFILE%\\controlplane-agent\\Scripts\\activate ^^&^^& python %USERPROFILE%\\controlplane-agent.py" /SC ONLOGON /RL HIGHEST /F
schtasks /Run /TN "ControlPlaneAgent"
echo Agent installed and scheduled.
`;
    }

    function refreshScript() {
      scriptPre.textContent = generateScript();
    }
    function applyTheme(name) {
      const themes = {
        default: {
          bg: "#0b0f19",
          panel: "#151b2b",
          panelAlt: "#1d2437",
          text: "#e8ecf5",
          muted: "#9aa4bf",
          accent: "#10a37f",
          accent2: "#06b6d4",
          danger: "#ff5c5c",
          border: "#1f2a44",
        },
        midnight: {
          bg: "#0c1117",
          panel: "#111827",
          panelAlt: "#1a2335",
          text: "#e5e7eb",
          muted: "#9ca3af",
          accent: "#14b8a6",
          accent2: "#0ea5e9",
          danger: "#f87171",
          border: "#1f2937",
        },
        graphite: {
          bg: "#0b0b10",
          panel: "#141420",
          panelAlt: "#1a1a2a",
          text: "#f4f4f5",
          muted: "#a1a1aa",
          accent: "#7c3aed",
          accent2: "#22d3ee",
          danger: "#f43f5e",
          border: "#1f1f2e",
        },
        obsidian: {
          bg: "#0d0f12",
          panel: "#151a21",
          panelAlt: "#1c2330",
          text: "#eaeff7",
          muted: "#9aa4b5",
          accent: "#fb923c",
          accent2: "#f97316",
          danger: "#ef4444",
          border: "#1f2733",
        },
        emerald: {
          bg: "#0b1414",
          panel: "#121c1d",
          panelAlt: "#182426",
          text: "#e6f4f1",
          muted: "#9fb3ad",
          accent: "#10b981",
          accent2: "#34d399",
          danger: "#f87171",
          border: "#1d2a2a",
        },
        indigo: {
          bg: "#0d1021",
          panel: "#16192b",
          panelAlt: "#1d2340",
          text: "#f3e8ff",
          muted: "#cbd5e1",
          accent: "#c084fc",
          accent2: "#ec4899",
          danger: "#fb7185",
          border: "#1f2437",
        },
      };
      const theme = themes[name] || themes.graphite;
      const root = document.documentElement;
      root.style.setProperty("--bg", theme.bg);
      root.style.setProperty("--panel", theme.panel);
      root.style.setProperty("--panel-alt", theme.panelAlt);
      root.style.setProperty("--text", theme.text);
      root.style.setProperty("--muted", theme.muted);
      root.style.setProperty("--accent", theme.accent);
      root.style.setProperty("--accent-2", theme.accent2);
      root.style.setProperty("--danger", theme.danger);
      root.style.setProperty("--border", theme.border);
    }

    function generateUninstallScript() {
      if (osSelect.value === "macos") {
        return `#!/usr/bin/env bash
launchctl unload ~/Library/LaunchAgents/com.controlplane.agent.plist 2>/dev/null || true
rm -f ~/Library/LaunchAgents/com.controlplane.agent.plist
rm -f ~/controlplane-agent.py
rm -rf ~/.controlplane-agent
echo "ControlPlane agent removed."`;
      }
      return `@echo off
schtasks /Delete /TN "ControlPlaneAgent" /F
del %USERPROFILE%\\controlplane-agent.py
rd /S /Q %USERPROFILE%\\controlplane-agent
echo ControlPlane agent removed.
`;
    }

    copyBtn.addEventListener("click", async () => {
      await copyText(scriptPre.textContent, copyBtn, "Copy script");
    });

    copyUninstallBtn.addEventListener("click", async () => {
      await copyText(generateUninstallScript(), copyUninstallBtn, "Copy uninstall");
    });
    themeSelect.addEventListener("change", () => {
      applyTheme(themeSelect.value);
      localStorage.setItem("cp_theme", themeSelect.value);
    });
    endpointsDiv.addEventListener("click", (ev) => {
      const btn = ev.target.closest("button[data-action]");
      if (!btn) return;
      const action = btn.dataset.action;
      const id = btn.dataset.id;
      if (action === "delete" && id) {
        deleteEndpoint(id);
        return;
      }
      if (action === "toggle") {
        const card = btn.closest(".endpoint-card");
        const detail = card?.querySelector(".endpoint-detail");
        if (detail) {
          detail.classList.toggle("show");
          card.classList.toggle("expanded");
          const expanded = detail.classList.contains("show");
          btn.textContent = expanded ? "Hide" : "Show";
          if (expanded) expandedIds.add(id);
          else expandedIds.delete(id);
        }
      }
    });

    osSelect.addEventListener("change", () => {
      scriptVisible = true;
      refreshScript();
    });
    tokenInput.addEventListener("input", () => {
      if (scriptVisible) refreshScript();
    });
    urlInput.addEventListener("input", () => {
      if (scriptVisible) refreshScript();
    });

    saveBtn.addEventListener("click", () => savePrefs());
    refreshBtn.addEventListener("click", () => { fetchStatus(); fetchEndpoints(); });
    applyTheme(themeSelect.value);
    if (scriptVisible) refreshScript();
    schedule();

    scriptToggleBtn.addEventListener("click", () => {
      scriptVisible = !scriptVisible;
      scriptPre.hidden = !scriptVisible;
      scriptToggleBtn.textContent = scriptVisible ? "Hide" : "Show";
      if (scriptVisible) refreshScript();
    });

    rawToggleBtn.addEventListener("click", () => {
      rawVisible = !rawVisible;
      raw.hidden = !rawVisible;
      rawToggleBtn.textContent = rawVisible ? "Hide" : "Show";
      toggleGrid.checked = rawVisible;
      gridCard.hidden = !rawVisible;
    });

    warningsToggleBtn.addEventListener("click", () => {
      const hidden = warningsList.hasAttribute("hidden");
      if (hidden) {
        warningsList.removeAttribute("hidden");
        warningsToggleBtn.textContent = "Hide";
        toggleWarnings.checked = true;
        warningsCard.hidden = false;
      } else {
        warningsList.setAttribute("hidden", "");
        warningsToggleBtn.textContent = "Show";
        toggleWarnings.checked = false;
        warningsCard.hidden = true;
      }
    });

    awakenBtn.addEventListener("click", () => {
      headerIcon.src = "/static/eyecon.png";
      if (faviconLink) {
        faviconLink.href = "/static/eyecon.png";
      }
      awakenBtn.textContent = "Awakened";
      awakenBtn.disabled = true;
    });

    onboardingToggle.addEventListener("click", () => {
      onboardingVisible = !onboardingVisible;
      onboardingContent.hidden = !onboardingVisible;
      onboardingToggle.textContent = onboardingVisible ? "Hide" : "Show";
      toggleOnboarding.checked = onboardingVisible;
    });

    lockdownToggle.addEventListener("change", () => {
      lockdown = lockdownToggle.checked;
      localStorage.setItem("cp_lockdown", lockdown ? "1" : "0");
      applyLockdown();
    });

    panelsToggleBtn.addEventListener("click", () => {
      const hidden = panelsDropdown.hasAttribute("hidden");
      if (hidden) {
        panelsDropdown.removeAttribute("hidden");
      } else {
        panelsDropdown.setAttribute("hidden", "");
      }
    });
    document.addEventListener("click", (ev) => {
      if (!panelsDropdown.hidden && !panelsDropdown.contains(ev.target) && !panelsToggleBtn.contains(ev.target)) {
        panelsDropdown.setAttribute("hidden", "");
      }
    });

    expandAllBtn.addEventListener("click", () => {
      expandAllActive = !expandAllActive;
      expandAllBtn.textContent = expandAllActive ? "Collapse all" : "Expand all";
      const cards = Array.from(document.querySelectorAll(".endpoint-card"));
      cards.forEach((cardEl) => {
        const id = cardEl.dataset.id;
        const detail = cardEl.querySelector(".endpoint-detail");
        const toggleBtn = cardEl.querySelector('button[data-action="toggle"]');
        if (!detail || !toggleBtn) return;
        if (expandAllActive) {
          detail.classList.add("show");
          cardEl.classList.add("expanded");
          expandedIds.add(id);
          toggleBtn.textContent = "Hide";
        } else {
          detail.classList.remove("show");
          cardEl.classList.remove("expanded");
          expandedIds.delete(id);
          toggleBtn.textContent = "Show";
        }
      });
    });

    function updateHealthPill() {
      if (!healthPill) return;
      const health = summarizeHealth(endpointsCache);
      const ts = lastRefresh
        ? new Date(lastRefresh).toLocaleTimeString([], { hour12: false })
        : "—";
      const status = lastError ? `Error: ${lastError}` : `Updated ${ts}`;
      healthPill.textContent = `Endpoints: ${health.active} active • ${health.stale} stale / ${endpointsCache.length} total • ${status}`;
    }

    toggleOnboarding.addEventListener("change", () => {
      onboardingVisible = toggleOnboarding.checked;
      onboardingCard.hidden = !onboardingVisible;
      onboardingContent.hidden = !onboardingVisible;
      onboardingToggle.textContent = onboardingVisible ? "Hide" : "Show";
    });

    toggleWarnings.addEventListener("change", () => {
      if (toggleWarnings.checked) {
        warningsCard.hidden = false;
        warningsList.removeAttribute("hidden");
        warningsToggleBtn.textContent = "Hide";
      } else {
        warningsCard.hidden = true;
        warningsList.setAttribute("hidden", "");
        warningsToggleBtn.textContent = "Show";
      }
    });

    filterStatus.addEventListener("change", renderDevices);
    filterOs.addEventListener("change", renderDevices);
    filterKind.addEventListener("change", renderDevices);
    filterSearch.addEventListener("input", () => {
      renderDevices();
    });
    filterReset.addEventListener("click", () => {
      filterStatus.value = "all";
      filterOs.value = "all";
      filterKind.value = "all";
      filterSearch.value = "";
      renderDevices();
    });
    function renderSummary() {
      if (!summaryGrid) return;
      const total = endpointsCache.length;
      const health = summarizeHealth(endpointsCache);
      const osCounts = { windows: 0, mac: 0, linux: 0, other: 0 };
      endpointsCache.forEach((e) => {
        const lowerOs = (e.os || "").toLowerCase();
        if (lowerOs.includes("windows")) osCounts.windows += 1;
        else if (lowerOs.includes("darwin") || lowerOs.includes("mac")) osCounts.mac += 1;
        else if (lowerOs.includes("linux")) osCounts.linux += 1;
        else osCounts.other += 1;
      });
      const rows = [
        card("Total endpoints", total),
        card("Active", health.active),
        card("Stale", health.stale),
        card("Windows", osCounts.windows),
        card("macOS", osCounts.mac),
        card("Linux", osCounts.linux),
        card("Other", osCounts.other),
      ];
      summaryGrid.innerHTML = rows.join("");
    }

    rotateTokenBtn.addEventListener("click", () => {
      const newToken = generateToken();
      tokenInput.value = newToken;
      localStorage.setItem("cp_token", newToken);
      if (scriptVisible) refreshScript();
      alert("New token generated. Update CONTROLPLANE_TOKEN in your server/container env and restart to apply.");
    });

    toggleGrid.addEventListener("change", () => {
      rawVisible = toggleGrid.checked;
      gridCard.hidden = !rawVisible;
      raw.hidden = !rawVisible;
      rawToggleBtn.textContent = rawVisible ? "Hide" : "Show";
    });

    async function copyText(text, btn, defaultLabel) {
      const original = btn.textContent;
      const fallback = () => {
        const ta = document.createElement("textarea");
        ta.value = text;
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
      };
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          await navigator.clipboard.writeText(text);
        } else {
          fallback();
        }
        btn.textContent = "Copied!";
      } catch (err) {
        try {
          fallback();
          btn.textContent = "Copied!";
        } catch (e) {
          btn.textContent = "Copy failed";
        }
      }
      setTimeout(() => (btn.textContent = defaultLabel), 1200);
    }

    function applyLockdown() {
      const lock = lockdown;
      // Hide/disable onboarding when locked
      onboardingCard.hidden = lock || !toggleOnboarding.checked;
      onboardingContent.hidden = lock || !onboardingVisible;
      onboardingToggle.textContent = onboardingVisible && !lock ? "Hide" : "Show";
      toggleOnboarding.checked = !lock && toggleOnboarding.checked;
      toggleOnboarding.disabled = lock;
      osSelect.disabled = lock;
      copyBtn.disabled = lock;
      copyUninstallBtn.disabled = lock;
      scriptToggleBtn.disabled = lock;
      tokenInput.disabled = lock;
      urlInput.disabled = lock;
      intervalInput.disabled = lock;
      scriptPre.hidden = true;
      scriptVisible = false;
    }
  </script>
</body>
</html>
    """
    )
    return HTMLResponse(content=html)


def _load_creds() -> tuple[str, str] | None:
    if not _creds_file.exists():
        return None
    try:
        data = json.loads(_creds_file.read_text(encoding="utf-8"))
        return data.get("username"), data.get("password_hash")
    except Exception:
        return None


def _save_creds(username: str, password: str) -> None:
    salt = os.environ.get("CONTROLPLANE_LOGIN_SALT", "salt")
    pw_hash = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
    _creds_file.write_text(
        json.dumps({"username": username, "password_hash": pw_hash}), encoding="utf-8"
    )


def _check_password(username: str, password: str) -> bool:
    creds = _load_creds()
    if not creds:
        return False
    stored_user, stored_hash = creds
    salt = os.environ.get("CONTROLPLANE_LOGIN_SALT", "salt")
    return (
        stored_user == username
        and stored_hash == hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
    )


def _make_session_cookie() -> str:
    secret = os.environ.get("CONTROLPLANE_SESSION_SECRET", "change-me")
    sig = hmac.new(secret.encode("utf-8"), b"auth", hashlib.sha256).hexdigest()
    return f"ok.{sig}"


def _is_authed(request: Request) -> bool:
    cookie = request.cookies.get(_session_cookie)
    if not cookie:
        return False
    secret = os.environ.get("CONTROLPLANE_SESSION_SECRET", "change-me")
    expected = hmac.new(secret.encode("utf-8"), b"auth", hashlib.sha256).hexdigest()
    return cookie == f"ok.{expected}"
