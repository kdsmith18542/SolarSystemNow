# PLAN.md — Project Roadmap & Implementation Plan

> **Solar System Now (`ss-now`)**  
> Linux desktop + local web dashboard for reviewing real, current, and historical data about Earth and its solar neighborhood.

---

## 1. Current State & Recent Accomplishments

The core infrastructure and high-priority reliability fixes have been successfully implemented:

- [x] **P0 Bugs Resolved**:
  - Fixed Moon rise/set location key mismatch (supports both singular and plural keys).
  - Isolated Open-Meteo per-location requests to prevent single-location network failures from failing the entire adapter.
  - Fixed sparkline fill path transparency and pen border.
  - Fixed Web UI refresh button remounting and MapView memory leaks / refs.
  - Replaced O(n) scan in `/api/events/{id}` with an O(1) primary key lookup.
  - Converted `/api/ingest` to run non-blocking in a background thread executor.
  - Supported dual static file resolution (`static/` and `dist/`).
- [x] **Database Hardening**:
  - R-Tree spatial indexing (`events_rtree`) populated on upsert for instant geographic queries.
  - Created `notifications` table and query/delivery tracking methods.
  - Implemented versioned migration framework in `Store.migrate()`.
  - Added daily auto-prune hook in `record_success()` to enforce retention budgets on snapshots, observations, and SDO assets.
  - Added `ssnow prune [--days N]` CLI command.
- [x] **Logging & Auto-Refresh**:
  - Built `ssnow_core/logging_config.py` with console and rotating file handlers.
  - Added `--log-level` CLI flag.
  - Added a 15-minute `QTimer` auto-refresh in `MainWindow`.
  - Refreshed all views across the board after ingest.
- [x] **Visual Polish**:
  - Realistic Moon Phase disk with smooth trigonometric crescent and terminator ellipse math.
  - Eliminated layout rebuild flicker in `NowView`, `MoonView`, and `SunView`.
  - Desktop map color-coded markers and frosted-glass legend.
  - SDO solar imagery served to the web frontend via `/api/sun/image`.
  - Desktop system tray alerts for significant earthquakes ($M \ge 6.0$) and geomagnetic storms ($Kp \ge 5.0$).
- [x] **Verification**: All 57 unit/adapter/smoke tests pass cleanly (`pytest -v`).

---

## 2. Verified Data Coverage (2026-11-21 Audit)

*Targeted at the "is anything missing?" question — confirmed present, no new providers needed.*

- [x] **Earthquakes**: USGS `M4.5+ Day` feed — magnitude, depth, lat/lon, `tsunami` flag, PAGER `alert`, `felt` count, `sig`, `magType`. UI now surfaces tsunami badge + felt count in Events detail and map popups.
- [x] **Tsunamis**: No standalone tsunami API needed — USGS `tsunami: 1` flag IS the tsunami trigger (same source PTWC uses). Verified in fixture (`nc75468702` has `tsunami: 1`). Surfaced as `🌊 TSUNAMI FLAG` badge + map popup + tray alert path.
- [x] **Volcanoes**: NASA EONET `volcanoes` category mapped to `volcano` in `ssnow_core/sources/eonet.py:13-25`. Same feed also covers wildfires, storms, floods. Map has dedicated Volcano+Fire layer.
- [x] **Asteroids**: NeoWs (keyed, 7-day) + JPL SBDB CAD (keyless, 30-day, asteroids AND comets). Stored as `category="neo"` with LD/km/velocity/size/Hazard in `extra_json`.
- [x] **Comets**: JPL CAD `jpl_cad` adapter (`ssnow_core/sources/cad.py`) — slash-designation detection (`1P/Halley`, `C/...`), kind split, SBDB links. No extra API key required.
- [x] **Streamer verdict (space + earth + weather for all-in-one tooling)**: CONFIRMED. OBS F11 fullscreen + SSE live stream + composite threat dial (now Bz/proton/Dst-aware) + aurora-localized dial + CME watch + multi-location weather/AQ/marine + tide stations + quake/tsunami/volcano layers covers the full loop a broadcaster needs (space weather → aurora call → local weather → hazard map) without leaving the app. Remaining gap is only CME *arrival countdown* (DONKI provides no arrival timestamp — currently shown as latest-CME watch verdict instead of fabricated countdown, per no-fabrication rule).

## 3. P1 Streamer Gap Ports (2026-11-21 — all free, MIT-keepable, US public domain / NASA)

*What Skov / S0 / SpaceWeatherLive / SolarHam / Ryan Hall show that we were missing — now ingested.*

- [x] **IMF Bz/Bt (P1.1)**: `swpc_mag` (`json/rtsw/rtsw_mag_1m.json`, active-spacecraft only, 5-min downsample) → `swpc:imf_bz_gsm/bt/by/bx`. Old `products/solar-wind/*` removed 2026-04-30 per SCN 26-21; `swpc_wind` rewritten to `rtsw_wind_1m.json` same pattern. Threat dial + tray alerts fire on Bz ≤ −5 nT.
- [x] **GOES proton flux (P1.2)**: `swpc_proton` (`json/goes/primary/integral-protons-1-day.json`) → `swpc:proton_flux_gte10/50/100MeV` (pfu). S-scale derived in views (S1 @ 10 pfu); alerts at S1+.
- [x] **Dst index (P1.5)**: `swpc_dst` (`products/kyoto-dst.json`, new object-array format) → `swpc:dst` (nT). Moderate ≤ −50, intense ≤ −100.
- [x] **Fireballs / bolides (P1.4)**: `jpl_fireball` (`fireball.api`, keyless) → `category="fireball"`, magnitude = impact kt, lat/lon mapped (S/W negative). Map + Events layers.
- [x] **SPC outlooks (P1.3)**: `spc_outlook` (Day1 cat/torn/wind/hail + Day2/3 cat `.lyr.geojson`, keyless) → `category="severe_outlook"`, magnitude = DN (2/3/4/5/6/8), centroid lat/lon + full polygon in `extra.geometry`. Desktop + web maps render translucent fills + centroid markers. Watches already covered via NWS alerts feed.
- Endpoints: `/api/sun/summary` extended (`bz_gsm`, `bt`, `dst`, `proton_gte10`); new `/api/spc/outlooks`, `/api/fireballs` (`/api/obs` + `/api/events` already generic).

## 4. P2 Ports (2026-11-21 — all free, MIT-keepable)

*Second wave from the same gap check — impact risk, solar context, imagery, ground-truth reports.*

- [x] **Sentry impact risk**: `sentry` (`ssd-api.jpl.nasa.gov/sentry.api` summary, keyless, 24h cadence) → top 40 by cumulative Palermo scale as `category="neo"` + `kind="sentry"` (PS magnitude, no LD → bottom of radar, honestly labelled). NeoView shows `IMPACT WATCH` + Sentry count; hazardous when PS ≥ −5.
- [x] **Solar cycle**: `swpc_cycle` (observed + predicted solar-cycle JSON, monthly) → `swpc:ssn_observed/f107_observed/ssn_predicted/f107_predicted`. Sun views show observed SSN + predicted; seeds a monthly point.
- [x] **Solar imagery wall**: 4 new channels reusing `SunImageryAdapter` — SDO 193Å (coronal holes), SDO 304Å, LASCO C2 + C3 — hourly cache. API: `/api/sun/images` + `/api/sun/images/{channel}`; web SunView renders wall; desktop keeps 171Å hero (QtWebEngine already heavy).
- [x] **Storm reports**: `iem_lsr` (IEM 24h LSR GeoJSON, free for any lawful purpose incl. commercial) → `category="storm"` + `kind="lsr"` (tornado/hail/wind, original units preserved). Rides the existing Storm layer + Events filter; detail badges added.
- Endpoints: `/api/sun/summary` gains `ssn/ssn_predicted`; `/api/sun/images` family covers the wall.

## 5. Close-Out: IDs, CME SIM Watch, HMI, Radar (2026-11-21)

*Yes — every event type now carries a stable unique ID, hardened for AI/collab use (see below). Last three honest gaps also closed.*

- [x] **Stable event IDs**: all adapters emit `{source}:{stable-key}` IDs. SPC/fireball/LSR hardened from order-/index-based IDs to SHA-1 content hashes (first-ring coords, full-row fields, `product_id`-or-hash). Same upstream record → same ID across refetches, reseeds, and clients. `test_event_ids_stable_and_unique` locks determinism + uniqueness. Old volatile fireball IDs (`fireball:{date}:{lat}:{lon}`) replaced — one-time duplicate rows possible in existing DBs.
- [x] **CME arrival watch (SIMULATION)**: no upstream arrival timestamp exists, so `/api/sim/cme-watch` auto-feeds the fastest Earth-directed DONKI CME + latest X-ray class through the existing `flare_arrival` ballistic scenario (±25% window). Desktop Sun + web SunView show `SIM arrival ~X–Yh`, always labelled model-not-observation per the no-fabrication rule.
- [x] **HMI magnetogram**: `sun_hmi` (`latest_512_HMIBC.jpg`, verified 200 JPEG) joins the imagery wall (now 6 channels).
- [x] **Radar overlay**: NEXRAD base-reflectivity via IEM WMS (free, any lawful purpose), toggled on both maps as live raster tiles — **nothing stored** (deliberate: tiles are ephemeral render data, not observations). US coverage only, labelled as such. RainViewer/Blitzortung stay out (NC/commercial licenses).

---

## 6. Active Roadmap

### Milestone 1: Creator & Broadcaster Features (High Impact)
*Targeted at YouTube space weather and science broadcasters (e.g. Dr. Tamitha Skov, Suspicious0bservers) and field observers.*

- [x] **OBS Studio Streamer Mode (F11 Toggle)**:
  - Full-screen, distraction-free mission-control display hiding window chrome, sidebar, and control buttons on F11 or Esc.
- [x] **Space Weather Threat Composite ("DEFCON" dial)**:
  - 4-level composite threat index (`QUIET` / `UNSETTLED` / `ELEVATED` / `STORM`) combining real-time Kp, GOES X-ray flare class, and solar wind velocity.
- [x] **"Aurora Tonight" Localized Visibility Dial**:
  - Automatically computes naked-eye visibility verdict (`Look Outside Now!`, `Possible on Horizon`, `Unlikely Tonight`) based on user's geographic latitude threshold vs. real-time Kp.
- [x] **CME Watch Widget (initial)**:
  - `SunView` shows latest DONKI CME with speed / type / Earth-directed verdict (`S/C-type or wide half-angle`). Full arrival *countdown* is intentionally NOT fabricated — DONKI provides no arrival timestamp. Counts as watch-live, countdown pending upstream data.
- [x] **Asteroids & Comets Tracker**:
  - New `NeoView` desktop tab + web `Asteroids` tab + `/api/neos` endpoint. Lunar-Distance radar strip, inner-solar-system distance schematic (explicitly NOT true orbits), PHA red badges, comet/cyan vs asteroid/lime colors, human sizes (`airliner / stadium / skyscraper`), JPL SBDB links. Tray alerts for PHA or `<1 LD` passes.

---

### Milestone 2: Data & Offline Enrichment

- [x] **Expand Seed Coverage for Offline Use**:
  - Now 28 of 33 sources seed offline (adds Kp forecast, SWPC alerts, X-ray, F10.7, RTSW wind/IMF, protons, GST, NWS alerts, aurora + 6 SDO/LASCO JPEGs). First launch shows quakes, hazards, Kp, CMEs, close approaches, bolides, outlooks, storm indices AND imagery. Unseedable by design: geomag/Open-Meteo/tides (need user locations/stations), Moon (computed live), DONKI FLR (disabled upstream).
- [x] **Settings Multi-Location Management**:
  - Full UI display and removal of saved locations and tide stations with real-time persistence.
- [x] **Events Detail Badges & Map Layer Toggles**:
  - `EventsView` detail dialog surfaces tsunami / PAGER / felt / NWS severity+expires+instruction / PHA / comet / CME speed badges (all previously ingested-but-hidden `extra_json`).
  - Desktop + web maps have smooth layer checkboxes (Quakes+Tsunami | Volcano+Fire | Storm/Flood/Alerts | Space weather | Other). Explicitly NOT a Google-Earth clone: Earth map stays 2D geographic; solar-system distances live in the separate Asteroids schematic. NEOs excluded from Earth map (no lat/lon) by design.
- [x] **Events Table Sorting & Map Cross-Linking**:
  - Desktop `EventsView` columns sort on click (sorting preserved across refresh); detail dialog has "Show on Map" (centers Map tab on the event, sticky until Reset). Web `Events.tsx` sorts by Time/Mag on header click.

---

### Milestone 3: Realtime Server-Client & Live Stream

- [x] **Server-Sent Events (SSE) Stream in FastAPI**:
  - Implemented `/api/stream/live` in `ssnow_web/api.py` with subscriber broadcasting on ingest cycles and heartbeat keep-alive. Web header shows ● LIVE / ○ offline and auto-refreshes every view on `ingest_complete`.
- [x] **Remote Server Connection Option**:
  - `ssnow_core/remote.py` `RemoteStore` duck-types the read subset of `Store` over HTTP (events, series, settings, sources, stats, imagery with an hourly disk cache, in-memory notifications). Desktop Settings has a server-connection section (QSettings `remote_mode` + `remote_base_url`, applies on restart); ingest becomes `POST /api/ingest` on the server. Unreachable server falls back to standalone with a logged warning. Secrets never leave the server (blank NASA key = "keep"). Backup export is disabled in remote mode. `/api/obs` gained an `order=asc|desc` param so latest-value lookups match local `latest_observations`.
- [x] **Docker Compose for Self-Hosting**:
  - `packaging/Dockerfile.web` + `packaging/docker-compose.yml` (`docker compose ... up -d`, data in `ssnow-data` volume). Compose config validated with `docker compose config`.

---

### Milestone 4: Packaging & Distribution

- [x] **AppImage Build Pipeline**:
  - Spec fixed (relative paths, `ssnow_core/data` bundled). Full PyInstaller build verified green; frozen GUI boots offscreen with no import errors. `appimagetool` final step needs its binary installed (not present here).
- [x] **Documentation Updates**:
  - `README.md` rewritten: 32 adapters, web dashboard, `prune`/`sim`/`ssnow-web` commands, data-integrity rules.
- [x] **Dependency Hygiene**:
  - `requirements.lock` regenerated from the working venv (was missing skyfield/uvicorn/respx).

---

## 7. Prioritized Execution Next Steps

| Task | Priority | Status | Focus |
|---|---|---|---|
| **Streamer / OBS Mode (F11)** | P1 | Completed | Desktop UI |
| **"Aurora Tonight" Dial** | P1 | Completed | NowView Dashboard |
| **Solar Activity Threat Index** | P1 | Completed | NowView Dashboard |
| **Asteroids & Comets Tracker (NeoView + CAD + /api/neos)** | P1 | Completed | Desktop + Web + Core |
| **Map Layer Toggles + Event Badges (tsunami/PHA/NWS/CME)** | P1 | Completed | Desktop + Web maps |
| **IMF Bz/Bt RTSW + wind rewrite (SCN 26-21)** | P1 | Completed | Core + Desktop + Web |
| **GOES Proton Flux (S-scale) + Dst** | P1 | Completed | Core + Desktop + Web |
| **JPL Fireballs + SPC Outlooks (fills)** | P1 | Completed | Core + Desktop + Web + API |
| **Sentry Impact Watch + Solar Cycle + Imagery Wall + LSR Reports** | P2 | Completed | Core + Desktop + Web + API |
| **Stable Event IDs (hash-based, AI/collab-ready)** | P2 | Completed | Core (SPC/fireball/LSR) + tests |
| **CME SIM Arrival Watch (ballistic, labelled model)** | P2 | Completed | API + Desktop + Web |
| **HMI Magnetogram + Radar Overlay (live tiles, unstored)** | P2 | Completed | Core + Desktop + Web maps |
| **CME Arrival Countdown (needs upstream arrival ts)** | P3 | Superseded by SIM watch | SunView |
| **Settings Location Delete/Reorder** | P2 | Completed | Desktop SettingsView |
| **SSE Live Stream Endpoint** | P2 | Completed | Web API + Live badge (`/api/stream/live`) |
| **Full Seed Coverage (33 Sources)** | P2 | Partial (28/33) | Core / Offline Fixtures |
| **Remote Server Mode (RemoteStore + Settings toggle)** | P2 | Completed | Core + Desktop |
| **Docker Compose Self-Hosting** | P2 | Completed | Packaging |
| **Events Table Sorting + Map Cross-Linking** | P2 | Completed | Desktop EventsView + MapView + Web |
| **AppImage Packaging Test** | P3 | Completed | Portable spec + data bundled, frozen GUI boots |
