# AGENTS.md — Contributor & AI Agent Guide for `ss-now`

Welcome to **Solar System Now (`ss-now`)**. This document provides essential architectural context, invariants, coding standards, and operational guidelines for AI coding agents and human contributors working on this codebase.

---

## 1. System Architecture & Component Boundaries

The project is structured into three distinct layers with strict boundaries:

```
┌────────────────────────────────────────────────────────┐
│  ssnow_desktop/ (PySide6 / Qt GUI)                     │
│  - Desktop views (Now, Events, Map, Sun, Moon, etc.)   │
│  - System tray alerts (QSystemTrayIcon)                │
│  - Custom widgets (PhaseDisk, Sparkline)               │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│  ssnow_core/ (Pure Python Engine & CLI)                     │
│  - SQLite Store (WAL mode, R-Tree, Notifications)           │
│  - Sources & Ingestion Adapters (32 enabled, 33 specs)      │
│  - Ingest Scheduler (run_due, backoff tracking)             │
│  - Deterministic Physics Simulations (flare, impact)   │
│  - Logging & Configuration                             │
└───────────────────────────▲────────────────────────────┘
                            │
┌───────────────────────────┴────────────────────────────┐
│  ssnow_web/ (FastAPI + React / Vite / Tailwind)        │
│  - REST API & static asset serving                     │
│  - React frontend (Vite builds into ../static/)        │
│  - MapLibre GL web mapping                             │
└────────────────────────────────────────────────────────┘
```

### ⚠️ Critical Invariants & Rules

1. **Strict Decoupling of `ssnow_core`**:
   - `ssnow_core` **MUST NEVER** import `PySide6`, `Qt`, or any GUI toolkit.
   - This invariant is strictly verified by automated tests (`tests/test_core_no_qt.py`).
2. **Data Integrity (No Fabricated Data)**:
   - Missing data renders as missing (`"—"` or `"no data"`).
   - **Never synthesize or fabricate observations**. If an API is offline or rate-limited, fail gracefully or rely on real cached snapshots.
   - Every view must preserve source attribution and upstream citations.
3. **Thread Safety in Storage**:
   - `Store` operations in [`ssnow_core/store.py`](file:///media/keith/Data2/ss-now/ssnow_core/store.py) use an internal `RLock` (`self._lock`) and transactional contexts (`with self.transaction()`).
   - SQLite is configured with WAL (`journal_mode=WAL`) and `synchronous=NORMAL`.
4. **Structured Logging**:
   - Never use `print()` in library or background worker code.
   - Use `get_logger(__name__)` from [`ssnow_core.logging_config`](file:///media/keith/Data2/ss-now/ssnow_core/logging_config.py).
5. **No Layout Destruction on Refresh**:
   - In desktop views (`ssnow_desktop/views/`), build the UI widget hierarchy once in `__init__()`.
   - The `refresh()` method must only update values, text, pixmaps, and charts in-place. Never delete and recreate layouts during refresh.

---

## 2. Directory Structure

- `ssnow_core/`
  - `models.py`: Pydantic models (`Event`, `Observation`, `SnapshotRecord`, `SourceState`).
  - `store.py`: SQLite persistence layer (events, observations, snapshots, assets, notifications, R-tree).
  - `scheduler.py`: Ingestion scheduling with deterministic priority and exponential backoff.
  - `logging_config.py`: Centralized rotating log handler and formatters.
  - `sources/`: Data adapters (USGS, SWPC Kp/X-ray/F10.7/RTSW wind/IMF/proton/Dst/solar-cycle, DONKI CME/GST, NeoWs, JPL CAD asteroids+comets, JPL fireballs, Sentry, SPC outlooks, IEM storm reports, SDO+LASCO imagery x5, NWS, OVATION aurora, Open-Meteo, Moon, Tides, etc.).
  - `sim/`: Physics simulation scenarios (`flare_arrival`, `impact_crater`).
  - `seed.py`: Initial offline database population from bundled fixtures.
  - `cli.py`: Command-line interface (`ssnow ingest`, `ssnow stats`, `ssnow prune`, `ssnow gui`, `ssnow sim`).
- `ssnow_desktop/`
  - `app.py`: Qt application entry point.
  - `main_window.py`: Sidebar navigation, `IngestWorker` thread, `QTimer` auto-refresh (15m), system tray alerts.
  - `views/`: Desktop view tabs (`now.py`, `events.py`, `map.py`, `sun.py`, `moon.py`, `neo.py`, `sources.py`, `settings.py`).
  - `views/widgets/`: Reusable Qt widgets (`sparkline.py`, `PhaseDisk`).
- `ssnow_web/`
  - `api.py`: FastAPI endpoints (incl. `/api/neos`, `/api/spc/outlooks`, `/api/fireballs`; `/api/sun/summary` carries bz/bt/dst/proton/ssn; `/api/sun/images` (6 channels) + `/api/sim/cme-watch` (auto-fed ballistic SIM).
  - `server.py`: Uvicorn launcher (`ssnow-web`).
  - `src/`: React TypeScript frontend (Dashboard, Events, MapView, SunView, MoonView, NeoView, SimView).
  - `vite.config.ts`: Builds into `/media/keith/Data2/ss-now/static/`.
- `tests/`:
  - `test_adapters.py`, `test_new_sources.py`: Fixture-based tests for all 32 enabled ingestion adapters.
  - `test_store.py`: Database operations, R-tree index, notifications, asset pruning, backoff.
  - `test_core_no_qt.py`: Enforces zero Qt imports in core.
  - `test_smoke_gui.py`: Offscreen GUI construction test.

---

## 3. Development Workflow & Commands

Activate the environment before running tasks:

```bash
source .venv/bin/activate
```

### Running Tests
Always run the full test suite after making changes:
```bash
pytest -v
```

### Running the CLI
```bash
# Check database storage stats
python -m ssnow_core.cli stats

# Trigger ingestion of due sources
python -m ssnow_core.cli ingest

# Prune snapshots & observations older than N days
python -m ssnow_core.cli prune --days 90
```

### Building the Web Frontend
Whenever modifying files in `ssnow_web/src/`:
```bash
cd ssnow_web
npm run build
```
This updates the production bundle in `static/` which is served by `ssnow_web/api.py`.

### Running the Web Server
```bash
python -m ssnow_web.server --port 8123
# Open http://localhost:8123 in browser
```

---

## 4. Key Implementation Details for Agents

### Location Settings Convention
Locations are stored as a JSON list under the `"locations"` setting key:
```json
[
  {"name": "Home", "lat": 40.7128, "lon": -74.0060, "key": "40.71,-74.01"}
]
```
When querying location, always check `locations = store.get_setting("locations") or []` and take `locations[0]` if available, falling back to `store.get_setting("location")` or the default (London).

### Notification System
Use the `notifications` table to record alerts:
```python
store.add_notification(
    notif_id="unique-id",
    event_id=optional_event_id,
    category="space_weather_alert",
    title="Geomagnetic Storm: Kp 6.0",
    severity="warning", # info | warning | critical
    fired_at=now
)
```
Undelivered notifications are queried via `store.pending_notifications()` and marked with `store.mark_notification_delivered(notif_id)`.

### Adding New Adapters
1. Inherit from `HttpAdapter` (in `ssnow_core/sources/base.py`) or implement the `Adapter` protocol.
2. Define the `SourceSpec` and register in `ssnow_core/sources/registry.py`.
3. Provide a mock JSON/text fixture in `tests/fixtures/` and add test coverage in `tests/test_new_sources.py`.
4. If the feed is keyless (like JPL CAD), leave `requires_key=False` so offline/seed users still get data.
5. Copy the fixture into `ssnow_core/data/seed/` and extend `SEED_SOURCES`/`SEED_FILES` in `ssnow_core/seed.py` when the data is valuable offline (NEOs, quakes).

---

## 5. Product Principles & Verified Decisions (2026-11-21)

### Map layers: smooth checkboxes, NOT a Google-Earth clone
- Earth map (`MapView` desktop + web) uses simple layer checkbox groups: Quakes+Tsunami | Volcano+Fire | Storm/Flood/Alerts | Space weather | Other. No 3D globe, no tilt/rotate.
- Space objects (NEOs) never appear on the Earth map (they have no lat/lon by design) — they live in the dedicated `NeoView` / web `Asteroids` tab with an LD radar strip + explicitly-labelled distance schematic (NOT true orbits, per no-fabrication rule).
- Rationale: we view more than Earth (Sun, Moon, asteroids, comets, solar wind). One geographic map + one solar-system schematic keeps it smooth and easy.

### Streamer / broadcaster tooling verdict: CONFIRMED
- OBS F11 fullscreen + SSE `/api/stream/live` + threat dial + aurora-localized dial + CME watch + multi-location weather/AQ/marine + tides + quake/tsunami/volcano layers = full all-in-one loop (space → aurora call → local weather → hazard map). Validated for space-weather and weather streamers; no extra providers required.
- P1 gap ports (2026-11-21, all US public domain / NASA, MIT-keepable): RTSW IMF Bz/Bt (`swpc_mag`, active-spacecraft only) + RTSW wind rewrite (`swpc_wind`, SCN 26-21), GOES proton flux (`swpc_proton`, S-scale), Kyoto Dst (`swpc_dst`), JPL fireballs (`jpl_fireball`), SPC Day1-3 outlooks (`spc_outlook`, polygon fills + centroids). Threat dial and tray alerts are Bz/proton/Dst-aware.
- Known gap: DONKI provides no CME arrival timestamp, so the widget shows latest-CME watch verdict rather than a fabricated countdown.

### Tsunami / volcano coverage: already ingested
- Tsunamis: USGS `tsunami` flag (`nc75468702` fixture has `tsunami: 1`) — surfaced as `🌊 TSUNAMI FLAG` badge + map popup. No separate tsunami API needed (same trigger PTWC uses).
- Volcanoes: EONET `volcanoes` → `volcano` category mapping; dedicated map layer. Wildfires/storms/floods come from the same EONET feed.

### NEO conventions
- Unify NeoWs (`miss_lunar` string, `hazardous` bool, `diameter_km_min/max`) and CAD (`dist_lunar` float, `hazardous_candidate`, `diameter_km`, `is_comet`) via a `neo_record`-style normalizer; sort by LD ascending, unknowns last; PHA red, comets cyan, asteroids lime; sizes humanized (`house / airliner / stadium`); distances in LD with km fallback (`1 LD = 384,400 km`).
- Comet detection (CAD): slash designation (`1P/Halley`, `C/...`) or `^\d+P$`; do NOT classify `99942 Apophis (2004 MN4)`-style names as comets.

### Stable event IDs (AI / collab contract)
- Every event ID is `{source}:{stable-key}` where the key derives from the upstream ID when one exists (`usgs:{feature_id}`, `nws:{urn}`, `sentry:{sentry-id}`, `cad:{des}:{cd}`) and from a SHA-1 content hash otherwise: SPC hashes day/hazard/VALID/label/rounded first-ring (`spc:{day}:{hazard}:{12hex}`), fireballs hash date/lat/lon/energy/impact (`fireball:{12hex}`), LSR falls back to a hash of valid/lat/lon/type/mag when `product_id` is absent.
- Same upstream record → same ID across refetches, reseeds, and clients. Never use list index in an ID (SPC polygon order churns). Locked by `test_event_ids_stable_and_unique`. This is what notifications, future AI labels, and cross-client references key on.

### New event categories: `fireball`, `severe_outlook`
- `fireball` (JPL CNEOS): magnitude = impact kt, lat/lon mapped (S/W negated); renders on Earth map (orange) + Events filter. Unlike `neo` (space objects, no lat/lon), fireballs have ground coordinates.
- `severe_outlook` (SPC): magnitude = DN (2 TSTM / 3 MRGL / 4 SLGT / 5 ENH / 6 MDT / 8 HIGH), centroid lat/lon + full polygon in `extra.geometry`; maps render translucent yellow fills + centroid markers; layer default ON.
- Both added to `Category`, desktop `EventsView`/`NowView` lists, web `Events.tsx`, and map colors/layers on both clients.

### RTSW notes (SCN 26-21)
- `swpc_wind` now reads `json/rtsw/rtsw_wind_1m.json` and `swpc_mag` reads `json/rtsw/rtsw_mag_1m.json` (old `products/solar-wind/*` deleted 2026-04-30); filter `active=true`, keep `source` in `extra_json` provenance; tolerate quoted-string numbers.

### Imagery + radar + CME-watch conventions
- Solar imagery channels (`sun_imagery` 171Å, `sun_sdo193`, `sun_sdo304`, `sun_hmi` magnetogram, `sun_lasco_c2/c3`) share `SunImageryAdapter` (URL-driven; `follow_redirects=True` for LASCO). Served via `/api/sun/images/{channel}`. Never fabricate a channel: HMI was only added after a live 200-JPEG HEAD check.
- Radar (IEM WMS NEXRAD) is a **live overlay only** — never stored in SQLite, never snapshotted. Toggles on both maps, US coverage labelled.
- `/api/sim/cme-watch` auto-feeds the fastest Earth-directed DONKI CME + latest X-ray class into the `flare_arrival` SIMULATION. Always render with the SIM label; never present ballistic output as an observation.
