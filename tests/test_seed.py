"""First-run seeding and bundled-ephemeris tests."""

from __future__ import annotations

from datetime import datetime, timezone

from ssnow_core.scheduler import utcnow
from ssnow_core.seed import seed_if_empty
from ssnow_core.sources.moon import MoonAdapter
from ssnow_core.sources.registry import SPECS


def _now() -> datetime:
    return datetime(2026, 11, 20, 21, 0, 0, tzinfo=timezone.utc)


def test_seed_if_empty_populates_fresh_db(tmp_store):
    assert tmp_store.event_count() == 0
    seeded = seed_if_empty(tmp_store)
    assert seeded > 0
    assert tmp_store.event_count() > 0
    assert tmp_store.stats()["observations"] > 0
    assert tmp_store.get_setting("seeded_at") is not None
    # Second call is a no-op.
    assert seed_if_empty(tmp_store) == 0


def test_seed_does_not_clobber_existing_data(tmp_store):
    from ssnow_core.models import Event

    tmp_store.upsert_events([
        Event(
            id="x:1",
            source="x",
            upstream_id="1",
            category="other",
            title="existing",
            occurred_at=_now(),
        )
    ])
    assert seed_if_empty(tmp_store) == 0
    assert tmp_store.event_count() == 1


def test_moon_uses_bundled_ephemeris(tmp_store):
    adapter = MoonAdapter(SPECS["moon"])
    report = adapter.ingest(tmp_store, None, _now())
    assert report.ok
    state = tmp_store.get_setting("moon_state")
    assert state is not None
    assert state["source"] == "skyfield"
    assert 0.0 <= state["illumination"] <= 1.0
    assert state["next_rise_utc"] or state["next_set_utc"]


def test_seed_includes_computed_moon_and_location_free_vortex(tmp_store):
    from ssnow_core.seed import SEED_SOURCES

    assert "moon" in SEED_SOURCES
    assert "openmeteo" in SEED_SOURCES
    assert "donki_flare" in SEED_SOURCES
    assert "geomag_poles" in SEED_SOURCES
    assert seed_if_empty(tmp_store) > 0

    moon_state = tmp_store.get_setting("moon_state")
    assert moon_state is not None
    assert moon_state["source"] in {"skyfield", "analytic-fallback"}

    vortex = tmp_store.get_series("openmeteo", "strato:vortex:60N:0E:windspeed_10hPa")
    assert len(vortex) == 3
    assert vortex[0].value == 104.8

    # Per-location weather still needs user locations; the seed must not invent it.
    assert tmp_store.get_latest_observation("openmeteo", "weather:51.5074,-0.1278:temperature_2m") is None

    flares = [e for e in tmp_store.query_events(limit=500) if e.category == "solar_flare"]
    assert len(flares) == 9
    assert all(e.latitude is None and e.longitude is None for e in flares)

    pole = tmp_store.get_latest_observation("geomag_poles", "geomag_pole:north:lat")
    assert pole is not None
    assert pole.extra_json["kind"] == "observed"
    assert tmp_store.get_latest_observation("geomag_poles", "geomag_pole:north:lat_forecast") is not None
