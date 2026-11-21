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
