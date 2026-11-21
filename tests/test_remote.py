"""Tests for RemoteStore (remote-server desktop mode)."""

from __future__ import annotations

import json

import httpx
import pytest

from ssnow_core.remote import RemoteReadOnlyError, RemoteStore


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="http://srv:8123")


def test_query_events_maps_params(tmp_path):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        body = {
            "count": 1,
            "events": [{
                "id": "usgs:x", "source": "usgs", "upstream_id": "x", "category": "earthquake",
                "title": "M 5.0", "occurred_at": "2026-11-20T00:00:00+00:00",
                "magnitude": 5.0, "magnitude_unit": "M", "extra": {"tsunami": 1},
            }],
        }
        return httpx.Response(200, json=body, request=request)

    store = RemoteStore("http://srv:8123", client=_client(handler))
    from datetime import datetime, timezone
    events = store.query_events(
        start=datetime(2026, 11, 1, tzinfo=timezone.utc),
        categories=["earthquake"], min_magnitude=4.5, limit=10,
    )
    assert len(events) == 1
    assert events[0].extra_json == {"tsunami": 1}
    assert seen["categories"] == "earthquake"
    assert seen["min_magnitude"] == "4.5"
    assert seen["limit"] == "10"
    assert "start" in seen
    store.close()


def test_get_series_and_latest_observations():
    points = [
        {"ts": "2026-11-20T20:00:00+00:00", "value": 3.0},
        {"ts": "2026-11-20T21:00:00+00:00", "value": 5.0, "extra": {"estimated": True}},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        pts = list(reversed(points)) if params.get("order") == "desc" else points
        return httpx.Response(200, json={"source": "swpc", "series": "x", "unit": "Kp", "count": 2, "points": pts[: int(params.get("limit", 99))]}, request=request)

    store = RemoteStore("http://srv:8123", client=_client(handler))
    series = store.get_series("swpc", "swpc:kp")
    assert [o.value for o in series] == [3.0, 5.0]
    latest = store.latest_observations("swpc", "swpc:kp")
    assert len(latest) == 1 and latest[0].value == 5.0
    assert latest[0].extra_json == {"estimated": True}
    store.close()


def test_settings_roundtrip_and_readonly():
    saved: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            saved.update(json.loads(request.content))
            return httpx.Response(200, json={"ok": True}, request=request)
        return httpx.Response(200, json={
            "locations": [{"name": "Home", "lat": 1.0, "lon": 2.0, "key": "1,2"}],
            "tide_stations": [], "nasa_api_key": True, "retention_days": 90,
        }, request=request)

    store = RemoteStore("http://srv:8123", client=_client(handler))
    assert store.get_setting("locations")[0]["name"] == "Home"
    assert store.get_setting("nasa_api_key") == ""  # secret never leaves the server
    assert store.get_setting("retention_days") == 90
    assert store.get_setting("nope", "dflt") == "dflt"
    store.set_setting("locations", [])
    assert saved == {"locations": []}
    with pytest.raises(RemoteReadOnlyError):
        store.set_setting("ephemeris_path", "/x")
    with pytest.raises(AttributeError):
        store.upsert_events([])
    store.close()


def test_remote_token_header_on_writes():
    tokens: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        tokens.append(request.headers.get("x-ssnow-token"))
        return httpx.Response(200, json={"ok": True}, request=request)

    store = RemoteStore("http://srv:8123", client=_client(handler), token="abc-123")
    store.set_setting("retention_days", 30)
    assert tokens[-1] == "abc-123"
    store.close()

    # Without a token no header is sent (public-trusted servers keep working).
    store = RemoteStore("http://srv:8123", client=_client(handler))
    store.set_setting("retention_days", 30)
    assert tokens[-1] is None
    store.close()


def test_source_states_and_stats_and_moon():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/sources":
            return httpx.Response(200, json={"sources": [{
                "source_id": "usgs", "name": "U", "domain": "d", "attribution": "a",
                "license": "l", "cadence_seconds": 600, "enabled": True,
                "last_attempt": None, "last_success": "2026-11-20T00:00:00+00:00",
                "last_error": None, "consecutive_failures": 0, "next_due": None,
                "records_ingested": 5,
            }]}, request=request)
        if path == "/api/stats":
            return httpx.Response(200, json={"events": 7}, request=request)
        if path == "/api/moon/state":
            return httpx.Response(200, json={"phase_name": "Full Moon"}, request=request)
        raise AssertionError(path)

    store = RemoteStore("http://srv:8123", client=_client(handler))
    states = store.all_source_states()
    assert states[0].source_id == "usgs" and states[0].records_ingested == 5
    assert store.stats() == {"events": 7}
    assert store.get_setting("moon_state")["phase_name"] == "Full Moon"
    store.close()


def test_latest_asset_download_and_cache(tmp_path):
    jpeg = b"\xff\xd8\xff" + b"\x00" * 64
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, content=jpeg, request=request, headers={"content-type": "image/jpeg"})

    store = RemoteStore("http://srv:8123", client=_client(handler))
    p1 = store.latest_asset("sun_imagery")
    assert p1 is not None and open(p1, "rb").read() == jpeg
    p2 = store.latest_asset("sun_imagery")
    assert p1 == p2 and calls["n"] == 1  # hourly cache: no second download
    store.close()


def test_notifications_in_memory():
    store = RemoteStore("http://srv:8123", client=_client(lambda r: httpx.Response(404, request=r)))
    store.add_notification("a", None, "earthquake", "M7!", "critical", None)
    store.add_notification("a", None, "earthquake", "M7!", "critical", None)  # dup ignored
    assert len(store.pending_notifications()) == 1
    store.mark_notification_delivered("a")
    assert store.pending_notifications() == []


def test_read_through_cache_avoids_repeat_requests():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={
            "locations": [{"name": "Home", "lat": 1.0, "lon": 2.0, "key": "1,2"}],
            "tide_stations": [], "nasa_api_key": False, "retention_days": 90,
        }, request=request)

    store = RemoteStore("http://srv:8123", client=_client(handler))
    assert store.get_setting("locations")[0]["name"] == "Home"
    assert store.get_setting("locations")[0]["name"] == "Home"
    assert calls["n"] == 1
    store.invalidate_cache()
    store.get_setting("locations")
    assert calls["n"] == 2
    store.close()


def test_prefetch_warms_cache_for_view_reads():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        path = request.url.path
        if path == "/api/settings":
            body = {
                "locations": [{"name": "Home", "lat": 1.0, "lon": 2.0, "key": "1,2"}],
                "tide_stations": [{"id": "8454000", "name": "Port"}],
                "nasa_api_key": False,
                "retention_days": 90,
            }
        elif path == "/api/sources":
            body = {"sources": []}
        elif path == "/api/events":
            body = {"count": 0, "events": []}
        elif path == "/api/obs":
            body = {"source": "x", "series": "x", "unit": None, "count": 0, "points": []}
        elif path == "/api/neos":
            body = {"count": 0, "pha": 0, "inside_moon": 0, "comets": 0, "neos": []}
        elif path == "/api/weather/now":
            body = {"count": 0, "locations": []}
        elif path == "/api/sim/cme-watch":
            body = {"available": False, "reason": "none"}
        else:
            body = {}
        return httpx.Response(200, json=body, request=request)

    store = RemoteStore("http://srv:8123", client=_client(handler))
    result = store.prefetch()
    assert result["ok"] > 10
    before = calls["n"]
    # These reads are exactly the keys prefetch warmed.
    assert store.get_setting("locations")[0]["name"] == "Home"
    assert store.get_latest_observation("swpc", "swpc:kp") is None
    assert store.query_events(limit=1, categories=["earthquake"]) == []
    assert calls["n"] == before
    store.close()
