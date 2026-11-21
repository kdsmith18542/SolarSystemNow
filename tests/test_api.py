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
    import ssnow_web.api as api

    # The module caches its Store in a global: reset it so every test opens
    # its own database instead of inheriting the first test's data.
    if api._store is not None:
        api._store.close()
    api._store = None
    with TestClient(app) as test_client:
        yield test_client
    if api._store is not None:
        api._store.close()
    api._store = None


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


def test_api_write_token_gate(client, monkeypatch):
    """Without SSNOW_API_TOKEN all endpoints are open. With it set, POSTs
    require the token while GETs stay public."""
    # Open by default.
    res = client.post("/api/settings", json={"retention_days": 42})
    assert res.status_code == 200

    monkeypatch.setenv("SSNOW_API_TOKEN", "secret-1")
    # Blocked without a token...
    assert client.post("/api/settings", json={"retention_days": 7}).status_code == 403
    assert client.post("/api/sim/run", json={"id": "flare_arrival", "params": {}}).status_code == 403
    assert client.post("/api/ingest").status_code == 403
    # ...allowed with X-SSNOW-Token or Bearer, GETs always public.
    assert client.post("/api/settings", json={"retention_days": 7}, headers={"X-SSNOW-Token": "secret-1"}).status_code == 200
    assert client.post("/api/settings", json={"retention_days": 7}, headers={"Authorization": "Bearer secret-1"}).status_code == 200
    assert client.post("/api/settings", json={"retention_days": 7}, headers={"X-SSNOW-Token": "wrong"}).status_code == 403
    assert client.get("/api/events").status_code == 200
    assert client.get("/api/sun/summary").status_code == 200


def test_api_weather_now(client):
    res = client.get("/api/weather/now")
    assert res.status_code == 200
    data = res.json()
    assert data["count"] == 0 and data["locations"] == []

    store = get_store()
    from datetime import datetime, timezone

    from ssnow_core.models import Observation

    NOW = datetime.now(timezone.utc)
    store.set_setting("locations", [{"name": "Home", "lat": 40.71, "lon": -74.01, "key": "40.71,-74.01"}])
    store.upsert_observations(
        [
            Observation(source="openmeteo", series="weather:40.71,-74.01:temperature_2m", ts=NOW, value=18.5, unit="°C"),
            Observation(source="openmeteo", series="weather:40.71,-74.01:wind_speed_10m", ts=NOW, value=22.0, unit="km/h"),
            Observation(source="openmeteo", series="air:40.71,-74.01:us_aqi", ts=NOW, value=35.0, unit="USAQI"),
            Observation(source="openmeteo", series="marine:40.71,-74.01:wave_height", ts=NOW, value=1.2, unit="m"),
        ]
    )
    res2 = client.get("/api/weather/now")
    data2 = res2.json()
    assert data2["count"] == 1
    row = data2["locations"][0]
    assert row["name"] == "Home"
    assert row["temp_c"]["value"] == pytest.approx(18.5)
    assert row["wind_kmh"]["value"] == pytest.approx(22.0)
    assert row["aqi"]["value"] == pytest.approx(35.0)
    assert row["wave_m"]["value"] == pytest.approx(1.2)
    assert row["sst_c"] is None


def test_api_sun_summary_new_fields(client):
    """Extended summary fields (proton channels, wind, aurora oval, declination)
    must always be present — null when no data, never fabricated."""
    store = get_store()
    # Startup seeding populates fixtures; clear observations so this test
    # exercises the explicit no-data contract.
    with store.transaction() as c:
        c.execute("DELETE FROM observations")

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
        assert data[key] is None  # cleared store: no data yet
    assert data["poles"] == {"north": None, "south": None}

    # With real observations the values surface.
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
    pole_ts = datetime(2025, 1, 1, tzinfo=timezone.utc)
    prev_ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
    store.upsert_observations(
        [
            Observation(source="geomag_poles", series="geomag_pole:north:lat", ts=prev_ts, value=85.958, unit="deg", extra_json={"year": 2024}),
            Observation(source="geomag_poles", series="geomag_pole:north:lon", ts=prev_ts, value=139.0, unit="deg", extra_json={"year": 2024}),
            Observation(source="geomag_poles", series="geomag_pole:north:lat", ts=pole_ts, value=85.958, unit="deg", extra_json={"year": 2025}),
            Observation(source="geomag_poles", series="geomag_pole:north:lon", ts=pole_ts, value=139.0, unit="deg", extra_json={"year": 2025}),
            Observation(source="geomag_poles", series="geomag_pole:north:lat_forecast", ts=datetime(2030, 1, 1, tzinfo=timezone.utc), value=84.723, unit="deg", extra_json={"year": 2030}),
            Observation(source="geomag_poles", series="geomag_pole:north:lon_forecast", ts=datetime(2030, 1, 1, tzinfo=timezone.utc), value=126.092, unit="deg", extra_json={"year": 2030}),
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
    assert data2["poles"]["north"]["drift_km"] == pytest.approx(0.0)
