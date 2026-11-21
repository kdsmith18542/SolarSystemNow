"""Storage layer tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ssnow_core.models import Event, Observation
from conftest import load_fixture, load_json_fixture

_NOW = datetime(2026, 11, 20, 21, 0, 0, tzinfo=timezone.utc)


def _event(eid: str, source: str = "usgs", category: str = "earthquake", magnitude: float | None = 5.0) -> Event:
    return Event(
        id=eid,
        source=source,
        upstream_id=eid,
        category=category,
        title=f"Event {eid}",
        occurred_at=_NOW,
        latitude=1.0,
        longitude=2.0,
        magnitude=magnitude,
        magnitude_unit="M",
    )


def test_upsert_and_query(tmp_store):
    assert tmp_store.upsert_events([_event("a")]) == 1
    assert tmp_store.event_count() == 1
    rows = tmp_store.query_events(categories=["earthquake"])
    assert len(rows) == 1
    assert rows[0].id == "a"
    assert rows[0].magnitude == 5.0


def test_upsert_is_idempotent(tmp_store):
    tmp_store.upsert_events([_event("a", magnitude=5.0)])
    tmp_store.upsert_events([_event("a", magnitude=5.5)])
    assert tmp_store.event_count() == 1
    assert tmp_store.query_events(limit=1)[0].magnitude == 5.5


def test_observations(tmp_store):
    obs = [
        Observation(source="swpc", series="swpc:kp", ts=_NOW, value=2.0, unit="Kp"),
        Observation(source="swpc", series="swpc:kp", ts=datetime(2026, 11, 20, 20, 0, tzinfo=timezone.utc), value=1.0, unit="Kp"),
    ]
    assert tmp_store.upsert_observations(obs) == 2
    latest = tmp_store.latest_observations("swpc", "swpc:kp")
    assert len(latest) == 1
    assert latest[0].value == 2.0


def test_snapshot_roundtrip_and_prune(tmp_store):
    rec = tmp_store.save_snapshot("usgs", "https://example.com/feed", b'{"x":1}', "application/json", status_code=200)
    assert rec.size_bytes > 0
    stats = tmp_store.stats()
    assert stats["snapshots"] == 1
    assert stats["snapshot_bytes"] > 0
    removed = tmp_store.prune_snapshots(retention_days=0)
    assert removed == 1
    assert tmp_store.stats()["snapshots"] == 0


def test_settings(tmp_store):
    tmp_store.set_setting("nasa_api_key", "DEMO_KEY")
    assert tmp_store.get_setting("nasa_api_key") == "DEMO_KEY"
    assert tmp_store.get_setting("missing", "default") == "default"


def test_export_backup(tmp_store, tmp_path):
    tmp_store.upsert_events([_event("a")])
    dest = tmp_path / "backup.tar.gz"
    path = tmp_store.export_backup(dest)
    assert path == dest
    assert dest.exists()
    assert dest.stat().st_size > 0


def test_success_resets_backoff(tmp_store):
    now = datetime(2026, 11, 20, 21, 0, 0, tzinfo=timezone.utc)
    tmp_store.begin_attempt("usgs", now)
    tmp_store.record_failure("usgs", now, "boom", 600)
    tmp_store.record_failure("usgs", now, "boom", 600)
    tmp_store.record_failure("usgs", now, "boom", 600)
    backed_off = [s for s in tmp_store.all_source_states() if s.source_id == "usgs"][0].next_due
    assert backed_off > now + timedelta(seconds=600)
    tmp_store.record_success("usgs", now, 3, 600)
    state = [s for s in tmp_store.all_source_states() if s.source_id == "usgs"][0]
    assert state.consecutive_failures == 0
    assert state.next_due == now + timedelta(seconds=600)


def test_failure_preserves_last_success(tmp_store):
    now = datetime(2026, 11, 20, 21, 0, 0, tzinfo=timezone.utc)
    tmp_store.begin_attempt("usgs", now)
    tmp_store.record_success("usgs", now, 3, 600)
    tmp_store.record_failure("usgs", now, "boom", 600)
    state = [s for s in tmp_store.all_source_states() if s.source_id == "usgs"][0]
    assert state.last_success == now
    assert state.last_error == "boom"
    assert state.consecutive_failures == 1


def test_get_event_by_id(tmp_store):
    tmp_store.upsert_events([_event("ev-123")])
    found = tmp_store.get_event_by_id("ev-123")
    assert found is not None
    assert found.id == "ev-123"
    assert tmp_store.get_event_by_id("non-existent") is None


def test_events_rtree_populated(tmp_store):
    tmp_store.upsert_events([_event("ev-rtree", magnitude=6.0)])
    # Query the R-Tree virtual table directly
    row = tmp_store._conn.execute(
        "SELECT count(*) FROM events_rtree WHERE min_lat >= 0.0 AND max_lat <= 2.0"
    ).fetchone()
    assert row[0] >= 1


def test_notifications_lifecycle(tmp_store):
    now = datetime(2026, 11, 20, 21, 0, 0, tzinfo=timezone.utc)
    tmp_store.add_notification(
        notif_id="notif-1",
        event_id="ev-123",
        category="space_weather_alert",
        title="High Kp Storm Alert",
        severity="warning",
        fired_at=now,
    )
    pending = tmp_store.pending_notifications()
    assert len(pending) == 1
    assert pending[0]["id"] == "notif-1"
    assert pending[0]["title"] == "High Kp Storm Alert"

    tmp_store.mark_notification_delivered("notif-1")
    assert len(tmp_store.pending_notifications()) == 0

    tmp_store.dismiss_notification("notif-1")
    row = tmp_store._conn.execute("SELECT dismissed_at FROM notifications WHERE id = 'notif-1'").fetchone()
    assert row[0] is not None


def test_prune_assets(tmp_store):
    now = datetime(2026, 11, 20, 21, 0, 0, tzinfo=timezone.utc)
    # Save dummy assets
    for i in range(10):
        tmp_store.save_asset(
            f"sun_{i}",
            "https://example.com/sun.jpg",
            b"\xff\xd8\xff\xe0" + b"x" * 20,
            "image/jpeg",
            status_code=200,
            fetched_at=now + timedelta(minutes=i),
        )
    assert tmp_store.stats()["assets"] == 10
    pruned = tmp_store.prune_assets_for_source("sun", keep_latest=5)
    assert pruned == 5
    assert tmp_store.stats()["assets"] == 5
