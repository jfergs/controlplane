from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from controlplane_server.app.main import create_app


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("CONTROLPLANE_TOKEN", "secret-token")
    return TestClient(create_app())


def test_root(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json() == {"name": "ControlPlane", "status": "ok"}


def test_health(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_status_requires_token(client: TestClient) -> None:
    resp = client.get("/api/status")
    assert resp.status_code == 401


def test_status_rejects_bad_token(client: TestClient) -> None:
    resp = client.get("/api/status", headers={"Authorization": "Bearer nope"})
    assert resp.status_code == 403


def test_status_succeeds_with_token(client: TestClient) -> None:
    resp = client.get("/api/status", headers={"Authorization": "Bearer secret-token"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["host"]
    assert data["disk_root"]["total_gb"] >= 0
