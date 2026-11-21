"""FastAPI endpoint tests."""

from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from ssnow_web.api import app, get_store


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SSNOW_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SSNOW_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("SSNOW_CACHE_DIR", str(tmp_path / "cache"))
    return TestClient(app)


def test_api_health(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "service": "ssnow-web"}


def test_api_stats(client):
    res = client.get("/api/stats")
    assert res.status_code == 200
    data = res.json()
    assert "events" in data
    assert "observations" in data


def test_api_events_lookup(client):
    res = client.get("/api/events")
    assert res.status_code == 200
    data = res.json()
    assert "count" in data
    assert "events" in data

    # 404 for non-existent event
    res404 = client.get("/api/events/non-existent-id")
    assert res404.status_code == 404


def test_api_sun_summary(client):
    res = client.get("/api/sun/summary")
    assert res.status_code == 200
    data = res.json()
    assert "kp" in data
    assert "xray" in data
    assert "f107" in data
