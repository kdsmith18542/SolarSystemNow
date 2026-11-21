"""Storage layer tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ssnow_core.models import Event, Observation
from ssnow_core.store import Store
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


def test_bbox_query_uses_rtree(tmp_store):
    from ssnow_core.models import Event as _Ev

    def ev(eid, lat, lon):
        return _Ev(
            id=eid, source="usgs", upstream_id=eid, category="earthquake",
            title=eid, occurred_at=_NOW, latitude=lat, longitude=lon, magnitude=5.0,
        )

    noloc = _Ev(
        id="noloc", source="neows", upstream_id="x", category="neo",
        title="noloc", occurred_at=_NOW,
    )
    tmp_store.upsert_events([ev("in1", 10.0, 20.0), ev("out1", -50.0, -60.0), noloc])
    hits = tmp_store.query_events(bbox=(0.0, 30.0, 10.0, 40.0), limit=50)
    assert sorted(e.id for e in hits) == ["in1"]
    # Non-geo events are excluded from bbox results but appear without bbox.
    all_ids = {e.id for e in tmp_store.query_events(limit=50)}
    assert {"in1", "out1", "noloc"} <= all_ids


def test_observations(tmp_store):
    obs = [
        Observation(source="swpc", series="swpc:kp", ts=_NOW, value=2.0, unit="Kp"),
        Observation(source="swpc", series="swpc:kp", ts=datetime(2026, 11, 20, 20, 0, tzinfo=timezone.utc), value=1.0, unit="Kp"),
    ]
    assert tmp_store.upsert_observations(obs) == 2
    latest = tmp_store.latest_observations("swpc", "swpc:kp")
    assert len(latest) == 1
    assert latest[0].value == 2.0


def test_legacy_database_self_heals_columns(tmp_path):
    """A database created before newer columns existed must open cleanly:
    missing columns are added, existing rows survive, writes work."""
    import sqlite3

    db = tmp_path / "data" / "legacy.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE events (
            id TEXT PRIMARY KEY, source TEXT NOT NULL, category TEXT NOT NULL,
            title TEXT NOT NULL, occurred_at TEXT NOT NULL, latitude REAL,
            longitude REAL, magnitude REAL, ingested_at TEXT NOT NULL
        );
        CREATE TABLE observations (
            source TEXT NOT NULL, series TEXT NOT NULL, ts TEXT NOT NULL,
            value REAL NOT NULL, unit TEXT,
            PRIMARY KEY (source, series, ts)
        );
        CREATE TABLE notifications (
            id TEXT PRIMARY KEY, category TEXT NOT NULL, title TEXT NOT NULL,
            severity TEXT NOT NULL, fired_at TEXT NOT NULL
        );
        INSERT INTO events VALUES ('old-1', 'usgs', 'earthquake', 'Old quake',
            '2026-11-19T00:00:00+00:00', 1.0, 2.0, 4.5, '2026-11-19T00:00:00+00:00');
        INSERT INTO observations VALUES ('swpc', 'swpc:kp', '2026-11-19T00:00:00+00:00', 3.0, 'Kp');
        """
    )
    conn.commit()
    conn.close()

    store = Store(db_path=db)
    try:
        with store.transaction() as c:
            events_cols = {r[1] for r in c.execute("PRAGMA table_info(events)").fetchall()}
            obs_cols = {r[1] for r in c.execute("PRAGMA table_info(observations)").fetchall()}
            notif_cols = {r[1] for r in c.execute("PRAGMA table_info(notifications)").fetchall()}
        assert {"upstream_id", "magnitude_unit", "raw_ref", "extra_json", "updated_at", "url", "depth_km"} <= events_cols
        assert "extra_json" in obs_cols
        assert {"dismissed_at", "delivered_desktop", "event_id"} <= notif_cols

        # Legacy rows survive with backfilled defaults.
        legacy = store.query_events(categories=["earthquake"], limit=10)
        assert [e.id for e in legacy] == ["old-1"]
        assert legacy[0].magnitude == 4.5
        kp = store.latest_observations("swpc", "swpc:kp")
        assert len(kp) == 1 and kp[0].value == 3.0

        # New writes work end-to-end.
        assert store.upsert_events([_event("new-1")]) == 1
        assert store.event_count() == 2
        store.add_notification(
            notif_id="n1", event_id=None, category="space_weather_alert", title="Test", severity="info", fired_at=_NOW
        )
        pending = store.pending_notifications()
        assert [n["id"] for n in pending] == ["n1"]
        store.mark_notification_delivered("n1")
        assert store.pending_notifications() == []

        # Reopening is a no-op (idempotent self-heal).
        store.close()
        reopened = Store(db_path=db)
        try:
            assert reopened.event_count() == 2
        finally:
            reopened.close()
    finally:
        store.close()


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
