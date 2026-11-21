"""Adapter tests with recorded fixtures and mocked HTTP transport."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx

from ssnow_core.models import Event
from ssnow_core.sources.donki import CMEAdapter, FlareAdapter
from ssnow_core.sources.eonet import EONETAdapter
from ssnow_core.sources.openmeteo import OpenMeteoAdapter
from ssnow_core.sources.registry import SPECS
from ssnow_core.sources.sun import SunImageryAdapter
from ssnow_core.sources.swpc import AlertsAdapter, KpAdapter
from ssnow_core.sources.usgs import USGSAdapter
from conftest import load_fixture


def _now() -> datetime:
    return datetime(2026, 11, 20, 21, 0, 0, tzinfo=timezone.utc)


def _client(content: bytes, status: int = 200, content_type: str = "application/json") -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=content, request=request, headers={"content-type": content_type})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_usgs_ingest(tmp_store):
    adapter = USGSAdapter(SPECS["usgs"])
    report = adapter.ingest(tmp_store, _client(load_fixture("usgs_quakes.geojson")), _now())
    assert report.ok
    assert len(report.events) == 3
    assert tmp_store.event_count() == 3
    assert report.events[0].id == "usgs:us6000ucd6"
    assert report.events[0].magnitude == 5.1


def test_eonet_dedupe_against_usgs(tmp_store):
    usgs_event = Event(
        id="usgs:us6000ucd6",
        source="usgs",
        upstream_id="us6000ucd6",
        category="earthquake",
        title="M 5.1 - Vanuatu",
            occurred_at=datetime(2026, 11, 20, 17, 53, 15, tzinfo=timezone.utc),
        latitude=-14.835,
        longitude=167.29,
        magnitude=5.1,
        magnitude_unit="M",
    )
    tmp_store.upsert_events([usgs_event])

    adapter = EONETAdapter(SPECS["eonet"])
    report = adapter.ingest(tmp_store, _client(load_fixture("eonet_events.json")), _now())
    assert report.ok
    events = [e for e in tmp_store.query_events(limit=500) if e.source == "eonet"]
    assert len(events) == 2  # two cyclones, earthquake deduped
    assert all(e.category != "earthquake" for e in events)
    assert tmp_store.event_count() == 3


def test_swpc_kp_ingest(tmp_store):
    adapter = KpAdapter(SPECS["swpc_kp"])
    report = adapter.ingest(tmp_store, _client(load_fixture("swpc_kp.json")), _now())
    assert report.ok
    series = tmp_store.get_series("swpc", "swpc:kp")
    assert len(series) == 6
    latest = series[-1]
    assert latest.value == 0.0


def test_openmeteo_ingest(tmp_store):
    tmp_store.set_setting("locations", [{"name": "London", "lat": 51.5074, "lon": -0.1278, "key": "51.5074,-0.1278"}])
    adapter = OpenMeteoAdapter(SPECS["openmeteo"])
    report = adapter.ingest(tmp_store, _client(load_fixture("openmeteo.json")), _now())
    assert report.ok
    series = tmp_store.latest_observations("openmeteo", "weather:51.5074,-0.1278:temperature_2m")
    assert len(series) == 1
    assert series[0].value == 7.9


def test_donki_cme_ingest(tmp_store):
    adapter = CMEAdapter(SPECS["donki_cme"])
    report = adapter.ingest(tmp_store, _client(load_fixture("donki_cme.json")), _now())
    assert report.ok
    assert len(report.events) == 1
    assert report.events[0].category == "cme"
    assert report.events[0].magnitude == 368.0


def test_donki_flr_ingest(tmp_store):
    adapter = FlareAdapter(SPECS["donki_flare"])
    report = adapter.ingest(tmp_store, _client(load_fixture("donki_flr.json")), _now())
    assert report.ok
    assert len(report.events) == 9
    first = report.events[0]
    assert first.category == "solar_flare"
    assert first.id == "donki:flare:2026-11-14T21:16:00-FLR-001"
    assert first.extra_json["class_type"] == "C2.8"
    # Solar-flare positions are heliographic source regions, never map pins.
    assert first.latitude is None and first.longitude is None


def test_sun_imagery_asset(tmp_store):
    jpeg = b"\xff\xd8\xfffake"
    content_type = "image/jpeg"
    adapter = SunImageryAdapter(SPECS["sun_imagery"])
    report = adapter.ingest(tmp_store, _client(jpeg, content_type=content_type), _now())
    assert report.ok
    assert report.assets == 1
    path = tmp_store.latest_asset("sun_imagery")
    assert path is not None
    assert __import__("pathlib").Path(path).read_bytes() == jpeg


def test_moon_fallback(tmp_store):
    import ssnow_core.sources.moon as moon_mod

    def boom(path, loader):
        raise FileNotFoundError(path)

    import ssnow_core.sources.moon

    ssnow_core.sources.moon.load_file_if_available = boom
    adapter = moon_mod.MoonAdapter(SPECS["moon"])
    report = adapter.ingest(tmp_store, None, _now())
    assert report.ok
    assert len(report.observations) == 2
    state = tmp_store.get_setting("moon_state")
    assert state is not None
    assert 0.0 <= state["illumination"] <= 1.0
    assert 0.0 <= state["phase_angle"] <= 360.0
    assert state["phase_name"]
