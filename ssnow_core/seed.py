"""First-run offline seeding from bundled fixtures.

Seeds a fresh database with the recorded fixture payloads through the real
adapter parse paths (no network), so the app shows real data on first launch
even offline. Seeded records are genuine captured upstream responses.
"""

from __future__ import annotations

from importlib import resources

SEED_SOURCES = (
    "usgs", "eonet", "swpc_kp", "donki_cme", "neows", "jpl_cad",
    "jpl_fireball", "spc_outlook", "swpc_dst", "sentry", "swpc_cycle", "iem_lsr",
    "swpc_kp_forecast", "swpc_alerts", "swpc_xray", "swpc_f107",
    "swpc_wind", "swpc_mag", "swpc_proton", "donki_gst",
    "nws_alerts", "aurora", "openmeteo", "moon", "donki_flare", "geomag_poles",
    "sun_imagery", "sun_sdo193", "sun_sdo304", "sun_hmi",
    "sun_lasco_c2", "sun_lasco_c3",
)
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
    "swpc_kp_forecast": "swpc_kp_forecast.json",
    "swpc_alerts": "swpc_alerts.json",
    "swpc_xray": "swpc_xray.json",
    "swpc_f107": "swpc_f107.json",
    "swpc_wind": "swpc_wind.json",
    "swpc_mag": "swpc_mag.json",
    "swpc_proton": "swpc_proton.json",
    "donki_gst": "donki_gst.json",
    "nws_alerts": "nws_alerts.json",
    "aurora": "aurora.json",
    "openmeteo": "openmeteo_vortex.json",
    "donki_flare": "donki_flr.json",
    "geomag_poles": "geomag_poles.json",
    "sun_imagery": "sun_imagery.jpg",
    "sun_sdo193": "sun_sdo193.jpg",
    "sun_sdo304": "sun_sdo304.jpg",
    "sun_hmi": "sun_hmi.jpg",
    "sun_lasco_c2": "sun_lasco_c2.jpg",
    "sun_lasco_c3": "sun_lasco_c3.jpg",
}

# Binary imagery seeds bypass snapshot/parse and go straight to the asset store.
IMAGE_SEEDS = {
    "sun_imagery", "sun_sdo193", "sun_sdo304", "sun_hmi",
    "sun_lasco_c2", "sun_lasco_c3",
}


def seed_if_empty(store) -> int:
    stats = store.stats()
    if stats["events"] or stats["observations"]:
        return 0
    if store.get_setting("seeded_at"):
        return 0

    import inspect

    from .logging_config import get_logger
    from .models import utcnow
    from .sources.registry import SPECS, build_adapter

    logger = get_logger("seed")
    now = utcnow()
    total = 0
    failures: list[str] = []
    for source_id in SEED_SOURCES:
        adapter = build_adapter(source_id)
        spec = SPECS[source_id]
        if adapter is None:
            failures.append(f"{source_id}: no adapter")
            continue
        if source_id == "moon":
            # Computed live from the bundled JPL ephemeris (no fixture needed).
            try:
                report = adapter.ingest(store, None, now)
            except Exception as exc:  # noqa: BLE001
                failures.append(f"moon: {exc}")
                continue
            if report.error:
                failures.append(f"moon: {report.error}")
                continue
            total += len(report.observations)
            continue
        try:
            payload = (
                resources.files("ssnow_core")
                .joinpath("data/seed")
                .joinpath(SEED_FILES[source_id])
                .read_bytes()
            )
        except (FileNotFoundError, ModuleNotFoundError) as exc:
            failures.append(f"{source_id}: {exc}")
            continue
        try:
            if source_id in IMAGE_SEEDS:
                # Genuine captured SDO/LASCO JPEGs straight into the asset store.
                store.save_asset(source_id, spec.url, payload, "image/jpeg", status_code=200, fetched_at=now)
                total += 1
                continue
            if source_id == "geomag_poles":
                store.save_snapshot(
                    source_id,
                    spec.url,
                    payload,
                    "application/json",
                    status_code=200,
                    fetched_at=now,
                )
                observations = adapter.parse_seed(payload, now)
                store.upsert_observations(observations)
                total += len(observations)
                continue
            if source_id == "openmeteo":
                # Location-independent stratospheric-vortex proxy only. Per-location
                # weather/marine/AQ still need user locations and a live ingest.
                store.save_snapshot(
                    "openmeteo:vortex:60N:0E",
                    spec.url,
                    payload,
                    "application/json",
                    status_code=200,
                    fetched_at=now,
                )
                _, observations = adapter.parse_vortex(payload, "vortex:60N:0E", now)
                store.upsert_observations(observations)
                total += len(observations)
                continue
            store.save_snapshot(source_id, spec.url, payload, "application/json", status_code=200, fetched_at=now)
            # NeoWsAdapter.parse(payload, now) vs HttpAdapter.parse(payload, content_type, now)
            params = inspect.signature(adapter.parse).parameters
            if "content_type" in params or len(params) >= 3:
                events, observations = adapter.parse(payload, "application/json", now)
            else:
                events, observations = adapter.parse(payload, now)
            # Some adapters (NeoWs, SPC, solar cycle) implement ingest() without
            # inheriting HttpAdapter.persist(); store their parsed rows directly.
            if hasattr(adapter, "persist"):
                adapter.persist(store, events, observations, now)
            else:
                store.upsert_events(events)
                store.upsert_observations(observations)
            total += len(events) + len(observations)
        except Exception as exc:  # noqa: BLE001
            logger.warning("seed %s failed: %s", source_id, exc)
            failures.append(f"{source_id}: {exc}")
    if failures:
        logger.warning(
            "seeded %d records; %d source(s) skipped/failed: %s",
            total,
            len(failures),
            "; ".join(failures[:5]),
        )
    if total > 0:
        store.set_setting("seeded_at", now.isoformat())
    else:
        logger.error("seed produced no records; will retry on next start")
    return total
