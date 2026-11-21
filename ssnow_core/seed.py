"""First-run offline seeding from bundled fixtures.

Seeds a fresh database with the recorded fixture payloads through the real
adapter parse paths (no network), so the app shows real data on first launch
even offline. Seeded records are genuine captured upstream responses.
"""

from __future__ import annotations

from importlib import resources

SEED_SOURCES = ("usgs", "eonet", "swpc_kp", "donki_cme", "neows", "jpl_cad", "jpl_fireball", "spc_outlook", "swpc_dst", "sentry", "swpc_cycle", "iem_lsr")
SEED_FILES = {
    "usgs": "usgs_quakes.geojson",
    "eonet": "eonet_events.json",
    "swpc_kp": "swpc_kp.json",
    "donki_cme": "donki_cme.json",
    "neows": "neows.json",
    "jpl_cad": "jpl_cad.json",
    "jpl_fireball": "fireball.json",
    "spc_outlook": "spc_outlook.geojson",
    "swpc_dst": "swpc_dst.json",
    "sentry": "sentry.json",
    "swpc_cycle": "swpc_cycle.json",
    "iem_lsr": "iem_lsr.geojson",
}


def seed_if_empty(store) -> int:
    stats = store.stats()
    if stats["events"] or stats["observations"]:
        return 0
    if store.get_setting("seeded_at"):
        return 0

    from .models import utcnow
    from .sources.registry import SPECS, build_adapter

    now = utcnow()
    total = 0
    for source_id in SEED_SOURCES:
        try:
            payload = (
                resources.files("ssnow_core")
                .joinpath("data/seed")
                .joinpath(SEED_FILES[source_id])
                .read_bytes()
            )
        except (FileNotFoundError, ModuleNotFoundError):
            continue
        adapter = build_adapter(source_id)
        spec = SPECS[source_id]
        try:
            store.save_snapshot(source_id, spec.url, payload, "application/json", status_code=200, fetched_at=now)
            # NeoWsAdapter.parse(payload, now) vs HttpAdapter.parse(payload, content_type, now)
            try:
                events, observations = adapter.parse(payload, "application/json", now)
            except TypeError:
                events, observations = adapter.parse(payload, now)
            adapter.persist(store, events, observations, now)
            total += len(events) + len(observations)
        except Exception:
            continue
    store.set_setting("seeded_at", now.isoformat())
    return total
