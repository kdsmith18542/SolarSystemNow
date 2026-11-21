"""Regression coverage for the 2026-11-20 deep audit."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from ssnow_core.models import Event, Observation
from ssnow_core.redact import redact_secrets, redact_url
from ssnow_core.remote import RemoteStore
from ssnow_core.sources.donki import CMEAdapter, is_earth_directed
from ssnow_core.sources.eonet import EONETAdapter
from ssnow_core.sources.moon import _fallback_moon, _phase_name
from ssnow_core.sources.nws import NWSAlertsAdapter
from ssnow_core.sources.openmeteo import OpenMeteoAdapter, _parse_time_to_epoch
from ssnow_core.sources.registry import SPECS
from ssnow_core.sources.swpc import AlertsAdapter
from conftest import load_fixture

NOW = datetime(2026, 11, 20, 21, 0, 0, tzinfo=timezone.utc)


def _event(eid: str, *, occurred_at=NOW, latitude=1.0, longitude=2.0, source="usgs") -> Event:
    return Event(
        id=eid,
        source=source,
        upstream_id=eid,
        category="earthquake",
        title=f"Event {eid}",
        occurred_at=occurred_at,
        latitude=latitude,
        longitude=longitude,
        magnitude=5.0,
    )


# ---- latest / tail query semantics ----------------------------------------


def test_latest_and_recent_series(tmp_store):
    tmp_store.upsert_observations(
        [
            Observation(source="swpc", series="swpc:kp", ts=NOW - timedelta(hours=2), value=1.0, unit="Kp"),
            Observation(source="swpc", series="swpc:kp", ts=NOW - timedelta(hours=1), value=4.0, unit="Kp"),
            Observation(source="swpc", series="swpc:kp", ts=NOW, value=7.0, unit="Kp"),
        ]
    )
    assert tmp_store.get_latest_observation("swpc", "swpc:kp").value == 7.0
    recent = tmp_store.get_recent_series("swpc", "swpc:kp", limit=2)
    assert [o.value for o in recent] == [4.0, 7.0]
    desc = tmp_store.get_series("swpc", "swpc:kp", limit=1, order="desc")
    assert [o.value for o in desc] == [7.0]


def test_latest_observations_window_query(tmp_store):
    tmp_store.upsert_observations(
        [
            Observation(source="swpc", series="swpc:kp", ts=NOW - timedelta(hours=1), value=1.0),
            Observation(source="swpc", series="swpc:kp", ts=NOW, value=6.0),
            Observation(source="swpc", series="swpc:kp_forecast", ts=NOW, value=3.0),
        ]
    )
    latest = tmp_store.latest_observations("swpc", "swpc:kp")
    values = {obs.series: obs.value for obs in latest}
    assert values == {"swpc:kp": 6.0, "swpc:kp_forecast": 3.0}


# ---- assets / retention ----------------------------------------------------


def test_assets_append_per_fetch_and_prune(tmp_store):
    for i in range(3):
        tmp_store.save_asset(
            "sun_imagery",
            "https://example.com/sun.jpg",
            b"\xff\xd8\xff" + bytes([i]),
            "image/jpeg",
            fetched_at=NOW + timedelta(minutes=i),
        )
    assert tmp_store.stats()["assets"] == 3
    assert len(list(tmp_store.assets_dir.iterdir())) == 3
    assert tmp_store.prune_assets_for_source("sun_imagery", keep_latest=1) == 2
    assert tmp_store.stats()["assets"] == 1
    assert len(list(tmp_store.assets_dir.iterdir())) == 1


def test_prune_assets_prefix_keeps_budget_per_channel(tmp_store):
    for source in ("sun_a", "sun_b"):
        for i in range(2):
            tmp_store.save_asset(
                source,
                "https://example.com/s.jpg",
                b"x",
                "image/jpeg",
                fetched_at=NOW + timedelta(minutes=i),
            )
    assert tmp_store.prune_assets_for_source("sun", keep_latest=1, prefix=True) == 2
    rows = tmp_store._conn.execute("SELECT source, COUNT(*) FROM assets GROUP BY source").fetchall()
    assert dict(rows) == {"sun_a": 1, "sun_b": 1}


def test_prune_preserves_solar_cycle_and_covers_weather_geomag_tides(tmp_store):
    old = NOW - timedelta(days=400)
    tmp_store.upsert_observations(
        [
            Observation(source="swpc", series="swpc:ssn_observed", ts=old, value=100.0),
            Observation(source="swpc", series="swpc:f107_observed", ts=old, value=120.0),
            Observation(source="swpc", series="swpc:kp", ts=old, value=1.0),
            Observation(source="openmeteo", series="weather:Home:temperature_2m", ts=old, value=10.0),
            Observation(source="openmeteo", series="air:Home:us_aqi", ts=old, value=10.0),
            Observation(source="geomag", series="geomag:Home:declination", ts=old, value=1.0),
            Observation(source="tides", series="tides:8454000:height", ts=old, value=1.0),
            Observation(source="aurora", series="aurora:intensity_max", ts=old, value=1.0),
        ]
    )
    deleted = tmp_store.prune_observations(90)
    assert deleted == 6
    remaining = {
        row[0]
        for row in tmp_store._conn.execute("SELECT series FROM observations").fetchall()
    }
    assert remaining == {"swpc:ssn_observed", "swpc:f107_observed"}


# ---- timestamps, R-tree, nearby --------------------------------------------


def test_event_timestamps_normalized_to_utc(tmp_store):
    tmp_store.upsert_events(
        [
            _event("a", occurred_at="2026-11-20T15:42:00-06:00"),
            _event("b", occurred_at="2026-11-20T18:00:00+00:00"),
            _event("c", occurred_at="2026-11-20T17:53:00+00:00"),
        ]
    )
    rows = tmp_store.query_events(limit=10)
    assert [event.id for event in rows] == ["a", "b", "c"]  # 21:42 UTC first
    raw = tmp_store._conn.execute("SELECT occurred_at FROM events ORDER BY id").fetchall()
    assert all(value.endswith("+00:00") for (value,) in raw)


def test_rtree_stale_rows_removed_and_backfilled(tmp_store):
    tmp_store.upsert_events([_event("geo", latitude=10.0, longitude=20.0)])
    bbox = (-15.0, 15.0, 10.0, 30.0)
    assert [e.id for e in tmp_store.query_events(bbox=bbox)] == ["geo"]

    # Coordinate removal must clear the spatial index too.
    tmp_store.upsert_events([_event("geo", latitude=None, longitude=None)])
    assert tmp_store.query_events(bbox=bbox) == []

    # Simulate a legacy database with events but no R-tree rows.
    tmp_store.upsert_events([_event("legacy", latitude=10.0, longitude=20.0)])
    tmp_store._conn.execute("DELETE FROM events_rtree")
    tmp_store._conn.execute("DELETE FROM meta WHERE key = 'rtree_backfill_version'")
    tmp_store._backfill_rtree()
    assert [e.id for e in tmp_store.query_events(bbox=bbox)] == ["legacy"]


def test_find_nearby_uses_timestamp_not_lexical_order(tmp_store):
    tmp_store.upsert_events(
        [
            _event("far", occurred_at=NOW - timedelta(minutes=90), source="eonet", latitude=0.0, longitude=0.0),
            _event("near", occurred_at=NOW - timedelta(minutes=30), source="eonet", latitude=0.0, longitude=0.0),
            _event("exact", occurred_at=NOW, source="eonet", latitude=0.0, longitude=0.0),
        ]
    )
    assert tmp_store.find_nearby_event("eonet", NOW, 0.0, 0.0).id == "exact"


# ---- redaction -------------------------------------------------------------


def test_redaction_helpers():
    url = "https://api.nasa.gov/DONKI/CME?startDate=x&api_key=SECRET&token=ALSO"
    redacted = redact_url(url)
    assert "SECRET" not in redacted and "ALSO" not in redacted
    assert "api_key=REDACTED" in redacted
    text = "403 for url 'https://api.nasa.gov/DONKI/CME?api_key=SECRET'"
    assert "SECRET" not in redact_secrets(text)


def test_store_redacts_snapshot_urls_and_errors(tmp_store):
    tmp_store.save_snapshot(
        "donki_cme",
        "https://api.nasa.gov/DONKI/CME?api_key=SECRET",
        b"{}",
        "application/json",
        fetched_at=NOW,
    )
    tmp_store.record_failure(
        "donki_cme", NOW, "403 for https://api.nasa.gov/DONKI/CME?api_key=SECRET"
    )
    snapshot_url = tmp_store._conn.execute("SELECT url FROM snapshots").fetchone()[0]
    state = tmp_store.all_source_states()[0]
    assert "SECRET" not in snapshot_url
    assert "SECRET" not in (state.last_error or "")


# ---- adapter fixes ---------------------------------------------------------


def test_swpc_alerts_use_issue_time_when_product_id_repeats():
    payload = json.dumps(
        [
            {
                "product_id": "ALTTP2",
                "issue_datetime": "2026-11-20T12:04:00",
                "message": "first",
            },
            {
                "product_id": "ALTTP2",
                "issue_datetime": "2026-11-20T13:04:00",
                "message": "second",
            },
        ]
    ).encode()
    events, _ = AlertsAdapter(SPECS["swpc_alerts"]).parse(payload, "application/json", NOW)
    assert len(events) == 2
    assert len({event.id for event in events}) == 2
    assert all("ALTTP2" in event.id for event in events)


def test_openmeteo_naive_times_are_utc():
    payload = json.dumps(
        {
            "hourly": {
                "time": ["2026-11-20T06:00"],
                "temperature_2m": [12.0],
                "precipitation_probability": [10],
                "wind_speed_10m": [5.0],
            },
            "daily": {
                "time": ["2026-11-20"],
                "sunrise": ["2026-11-20T07:00"],
                "sunset": ["2026-11-20T17:00"],
            },
        }
    ).encode()
    _, observations = OpenMeteoAdapter(SPECS["openmeteo"]).parse(payload, "Home", NOW)
    hourly = [o for o in observations if o.series.endswith("temperature_2m")][0]
    assert hourly.ts == datetime(2026, 11, 20, 6, tzinfo=timezone.utc)
    sunrise = [o for o in observations if o.series.endswith("sunrise")][0]
    assert sunrise.value == datetime(2026, 11, 20, 7, tzinfo=timezone.utc).timestamp()
    assert _parse_time_to_epoch("2026-11-20T06:00") == datetime(
        2026, 11, 20, 6, tzinfo=timezone.utc
    ).timestamp()


def test_cme_heliographic_coordinates_not_terrestrial(tmp_store):
    report = CMEAdapter(SPECS["donki_cme"]).ingest(
        tmp_store,
        httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    content=load_fixture("donki_cme.json"),
                    request=request,
                    headers={"content-type": "application/json"},
                )
            )
        ),
        NOW,
    )
    assert report.ok
    event = report.events[0]
    assert event.latitude is None and event.longitude is None
    assert event.extra_json["stlon"] == 172.0
    assert event.extra_json["coordinate_frame"] == "heliographic"
    assert not is_earth_directed(event.extra_json)


def test_nws_multipolygon_centroid():
    payload = json.dumps(
        {
            "features": [
                {
                    "properties": {
                        "id": "urn:test",
                        "event": "Flood Warning",
                        "severity": "Severe",
                        "sent": "2026-11-20T20:00:00Z",
                    },
                    "geometry": {
                        "type": "MultiPolygon",
                        "coordinates": [
                            [[[-110.0, 40.0], [-109.0, 40.0], [-109.0, 41.0], [-110.0, 40.0]]]
                        ],
                    },
                }
            ]
        }
    ).encode()
    events, _ = NWSAlertsAdapter(SPECS["nws_alerts"]).parse(payload, "application/json", NOW)
    assert events[0].latitude == pytest.approx(40.25, abs=0.01)
    assert events[0].longitude == pytest.approx(-109.5, abs=0.01)


def test_eonet_polygon_does_not_break_feed():
    payload = json.dumps(
        {
            "events": [
                {
                    "id": "E1",
                    "title": "Wildfire",
                    "categories": [{"id": "wildfires"}],
                    "geometry": [
                        {
                            "type": "Polygon",
                            "date": "2026-11-20T20:00:00Z",
                            "coordinates": [[[-120.0, 35.0], [-119.0, 35.0], [-119.0, 36.0], [-120.0, 35.0]]],
                        }
                    ],
                }
            ]
        }
    ).encode()
    events, _ = EONETAdapter(SPECS["eonet"]).parse(payload, "application/json", NOW)
    assert len(events) == 1
    assert events[0].latitude == pytest.approx(35.25, abs=0.01)


def test_moon_waning_phases_and_no_fake_distance():
    assert _phase_name(225) == "Waning Gibbous"
    assert _phase_name(315) == "Waning Crescent"
    fallback = _fallback_moon(NOW)
    assert fallback["distance_km"] is None
    assert 0 <= fallback["phase_angle"] < 360


def test_remote_store_rejects_malformed_observations():
    remote = RemoteStore("http://example.invalid")
    try:
        assert remote._obs_from_dict("s", "x", {}) is None
        assert remote._obs_from_dict("s", "x", {"ts": "bad", "value": 1}) is None
        assert remote._obs_from_dict("s", "x", {"ts": NOW.isoformat(), "value": None}) is None
        valid = remote._obs_from_dict("s", "x", {"ts": NOW.isoformat(), "value": "1.5"})
        assert valid is not None and valid.value == 1.5
    finally:
        remote.close()


# ---- API regressions -------------------------------------------------------


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    monkeypatch.setenv("SSNOW_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SSNOW_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("SSNOW_CACHE_DIR", str(tmp_path / "cache"))
    import ssnow_web.api as api

    if api._store is not None:
        api._store.close()
    api._store = None
    with TestClient(api.app) as client:
        yield client
    if api._store is not None:
        api._store.close()
    api._store = None


def test_api_assets_path_traversal_blocked(api_client):
    for path in ("/assets/%2Fetc%2Fpasswd", "/assets/..%2F..%2Fpyproject.toml"):
        response = api_client.get(path)
        assert response.status_code == 404


def test_api_obs_desc_returns_newest_not_oldest(api_client):
    import ssnow_web.api as api

    store = api.get_store()
    with store.transaction() as cursor:
        cursor.execute("DELETE FROM observations")
    base = NOW - timedelta(seconds=10005)
    store.upsert_observations(
        [
            Observation(source="swpc", series="swpc:kp", ts=base + timedelta(seconds=i), value=float(i))
            for i in range(10005)
        ]
    )
    response = api_client.get(
        "/api/obs",
        params={"source": "swpc", "series": "swpc:kp", "limit": 1, "order": "desc"},
    )
    assert response.status_code == 200
    assert response.json()["points"][0]["value"] == 10004.0


def test_api_sun_summary_uses_latest_observation(api_client):
    import ssnow_web.api as api

    store = api.get_store()
    with store.transaction() as cursor:
        cursor.execute("DELETE FROM observations")
    store.upsert_observations(
        [
            Observation(
                source="swpc",
                series="swpc:xray_flux",
                ts=NOW - timedelta(hours=2),
                value=2e-6,
                extra_json={"class": "C"},
            ),
            Observation(
                source="swpc",
                series="swpc:xray_flux",
                ts=NOW,
                value=2e-5,
                extra_json={"class": "M"},
            ),
        ]
    )
    data = api_client.get("/api/sun/summary").json()
    assert data["xray"]["class"] == "M"


def test_api_sources_lists_never_run_specs(api_client):
    data = api_client.get("/api/sources").json()
    assert len(data["sources"]) == len(SPECS)
    assert sum(1 for row in data["sources"] if row["enabled"]) == 32


def test_api_settings_validation_prevents_corruption(api_client):
    bad = api_client.post("/api/settings", json={"locations": "oops"})
    assert bad.status_code == 422
    assert api_client.get("/api/weather/now").status_code == 200

    bad_retention = api_client.post("/api/settings", json={"retention_days": -1})
    assert bad_retention.status_code == 422

    good = api_client.post(
        "/api/settings",
        json={"locations": [{"name": "Home", "lat": 40.71, "lon": -74.01, "key": "40.71,-74.01"}]},
    )
    assert good.status_code == 200
    assert api_client.get("/api/weather/now").status_code == 200


def test_api_settings_get_requires_token_when_configured(api_client, monkeypatch):
    monkeypatch.setenv("SSNOW_API_TOKEN", "secret-1")
    assert api_client.get("/api/settings").status_code == 403
    assert api_client.get("/api/settings", headers={"X-SSNOW-Token": "secret-1"}).status_code == 200
    # Public upstream data stays public.
    assert api_client.get("/api/events").status_code == 200
    assert api_client.get("/api/sun/summary").status_code == 200


def test_api_sources_error_is_redacted(api_client):
    import ssnow_web.api as api

    api.get_store().record_failure(
        "donki_cme", NOW, "403 for https://api.nasa.gov/DONKI/CME?api_key=SECRET"
    )
    row = [s for s in api_client.get("/api/sources").json()["sources"] if s["source_id"] == "donki_cme"][0]
    assert "SECRET" not in (row["last_error"] or "")
    assert row["last_error"]


def test_openmeteo_requests_utc_timezone(tmp_store):
    tmp_store.set_setting(
        "locations",
        [{"name": "Home", "lat": 40.71, "lon": -74.01, "key": "40.71,-74.01"}],
    )
    urls = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(request.url)
        return httpx.Response(
            200,
            content=b'{"hourly": {}, "daily": {}}',
            request=request,
            headers={"content-type": "application/json"},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        OpenMeteoAdapter(SPECS["openmeteo"]).ingest(tmp_store, client, NOW)
    weather = [url for url in urls if url.params.get("timezone") is not None]
    assert weather, "expected a weather request"
    assert all(url.params["timezone"] == "UTC" for url in weather)


def test_sentry_replaces_current_top_set(tmp_store):
    from ssnow_core.sources.sentry import SentryAdapter

    old = Event(
        id="sentry:old",
        source="sentry",
        upstream_id="old",
        category="neo",
        title="old sentry object",
        occurred_at=NOW,
        extra_json={"kind": "sentry"},
    )
    tmp_store.upsert_events([old])
    new = Event(
        id="sentry:new",
        source="sentry",
        upstream_id="new",
        category="neo",
        title="new sentry object",
        occurred_at=NOW,
        extra_json={"kind": "sentry"},
    )
    SentryAdapter(SPECS["sentry"]).persist(tmp_store, [new], [], NOW)
    ids = {event.id for event in tmp_store.query_events(categories=["neo"], limit=50)}
    assert ids == {"sentry:new"}


def test_legacy_offset_timestamps_are_migrated(tmp_store):
    tmp_store._conn.execute("DELETE FROM meta WHERE key = 'timestamps_utc_version'")
    tmp_store._conn.execute(
        """
        INSERT INTO events (id, source, upstream_id, category, title, occurred_at, extra_json, ingested_at)
        VALUES ('legacy-offset', 'nws', 'u', 'weather_alert', 't',
                '2026-11-20T15:42:00-06:00', '{}', '2026-11-20T21:42:00+00:00')
        """
    )
    tmp_store._conn.commit()
    tmp_store._normalize_legacy_event_timestamps()
    row = tmp_store._conn.execute(
        "SELECT occurred_at FROM events WHERE id = 'legacy-offset'"
    ).fetchone()
    assert row[0] == "2026-11-20T21:42:00+00:00"
