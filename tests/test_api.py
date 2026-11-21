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


def test_api_sun_summary_new_fields(client):
    """Extended summary fields (proton channels, wind, aurora oval, declination)
    must always be present — null when no data, never fabricated."""
    res = client.get("/api/sun/summary")
    assert res.status_code == 200
    data = res.json()
    for key in (
        "proton_gte50",
        "proton_gte100",
        "wind_speed",
        "wind_density",
        "aurora_oval",
        "aurora_mean",
        "declination",
    ):
        assert key in data
        assert data[key] is None  # empty temp store: no data yet

    # With real observations the values surface.
    store = get_store()
    from datetime import datetime, timezone

    from ssnow_core.models import Observation

    NOW = datetime.now(timezone.utc)

    store.upsert_observations(
        [
            Observation(source="swpc", series="swpc:solarwind_speed", ts=NOW, value=412.0, unit="km/s"),
            Observation(source="swpc", series="swpc:solarwind_density", ts=NOW, value=5.2, unit="p/cc"),
            Observation(source="swpc", series="swpc:proton_flux_gte50MeV", ts=NOW, value=0.31, unit="pfu"),
            Observation(source="aurora", series="aurora:oval_equatorward_deg", ts=NOW, value=58.4, unit="deg"),
        ]
    )
    store.set_setting(
        "locations",
        [{"name": "Home", "lat": 40.71, "lon": -74.01, "key": "40.71,-74.01"}],
    )
    store.upsert_observations(
        [
            Observation(
                source="geomag",
                series="geomag:40.71,-74.01:declination",
                ts=NOW,
                value=-13.2,
                unit="deg",
            )
        ]
    )
    res2 = client.get("/api/sun/summary")
    data2 = res2.json()
    assert data2["wind_speed"]["value"] == pytest.approx(412.0)
    assert data2["wind_density"]["value"] == pytest.approx(5.2)
    assert data2["proton_gte50"]["value"] == pytest.approx(0.31)
    assert data2["aurora_oval"]["value"] == pytest.approx(58.4)
    assert data2["declination"]["value"] == pytest.approx(-13.2)
    assert data2["declination"]["location"] == "Home"
