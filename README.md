# Solar System Now (ss-now)

[![CI](https://github.com/kdsmith18542/SolarSystemNow/actions/workflows/ci.yml/badge.svg)](https://github.com/kdsmith18542/SolarSystemNow/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/kdsmith18542/SolarSystemNow)](https://github.com/kdsmith18542/SolarSystemNow/releases)

Linux desktop + local web dashboard for reviewing **current and historical real data** about Earth and its solar neighborhood: earthquakes, tsunamis, volcanoes, storms, wildfires, floods, weather, space weather (Kp, solar wind, IMF Bz, flares, protons, Dst), the Sun (SDO/LASCO imagery), the Moon, and near-Earth asteroids, comets, fireballs and impact risk. No fabricated data, no server required, no hosting costs.

![Desktop Now view](docs/screenshots/desktop-now.png)
*Desktop: composite threat dial, Kp card, aurora verdict, quake + CME watch, Kp trend (Bz/proton/Dst live in the Sun view and streamer ribbon).*

![Web dashboard](docs/screenshots/web-dashboard.png)
*Web dashboard: same live data — threat hero, solar-wind/aurora metrics, per-location weather, event table with category chips.*

![OBS stream overlay](docs/screenshots/web-stream.png)
*`/stream`: chrome-free OBS browser-source overlay (`?compact=1`, `?bg=transparent`).*

## Architecture

- `ssnow_core/` — pure-Python library: 33 ingestion adapters, SQLite store (WAL + R-Tree + notifications), scheduler, deterministic physics sims, CLI. No Qt imports (enforced by test).
- `ssnow_desktop/` — PySide6/Qt GUI: Now, Events, Map, Sun, Moon, Asteroids, Sources, Settings. System-tray alerts, OBS streamer mode (F11).
- `ssnow_web/` — FastAPI + React/Tailwind/MapLibre, SSE live stream, builds into `static/`.
- Data sources (all free, public domain / permissive): USGS, NASA EONET, Open-Meteo, NOAA SWPC (Kp, X-ray, F10.7, RTSW wind/IMF, protons, Dst, solar cycle), NASA DONKI, JPL NeoWs/CAD/fireballs/Sentry, NOAA SPC outlooks, IEM storm reports, NWS alerts, OVATION aurora, geomag + historical magnetic poles, SDO/LASCO imagery, Skyfield Moon.
- Local SQLite database + gzipped raw snapshots; steady-state storage is single-digit GB.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev,gui,web]
```

## Run

```bash
# ingest due sources once
ssnow ingest

# stats
ssnow stats

# prune snapshots & observations older than N days
ssnow prune --days 90

# launch desktop GUI
ssnow gui

# run a deterministic physics simulation (labels SIMULATION, never a forecast)
ssnow sim --list
ssnow sim --id flare_arrival --param cme_speed_km_s=800

# web dashboard (needs npm run build in ssnow_web/ first)
ssnow-web --port 8123   # binds 127.0.0.1 by default
```

Environment overrides: `SSNOW_DATA_DIR`, `SSNOW_CONFIG_DIR`, `SSNOW_CACHE_DIR`, `SSNOW_API_TOKEN`, `SSNOW_CORS_ORIGINS`. Extra flags: `--log-level`.

Frontend checks: `cd ssnow_web && npm run typecheck && npm run build` (CI runs both).

## Remote server mode (desktop ↔ ssnow-web)

Run `ssnow-web` on a home server/NAS and point the desktop at it:

1. Start the server: `ssnow-web --port 8123` (or `docker compose`, below).
2. Desktop → **Settings → Server connection** → tick the box, enter `http://host:8123`, Save, restart.
3. Ingest now happens server-side (`POST /api/ingest`); the desktop reads over HTTP and shows `(remote server)` in the title.

If the server is unreachable at startup the desktop falls back to standalone with a logged warning. The NASA key never leaves the server; leaving the key field blank keeps the stored one. Backup export is standalone-only.

Set `SSNOW_API_TOKEN` on the server to require a token for `POST /api/ingest`, `/api/settings`, `/api/sim/run` and for reading `/api/settings` (header `X-SSNOW-Token` or `Authorization: Bearer …`); paste the same token into the desktop Settings server section and the web Settings tab. Public upstream GETs stay public. In remote mode the desktop also follows the server's SSE live stream, so it refreshes the moment an ingest finishes.

## Self-hosting (Docker)

```bash
docker compose -f packaging/docker-compose.yml up -d --build
# http://127.0.0.1:8123 — data persists in the ssnow-data volume.
# The image builds the React bundle from source (multi-stage); no stale static/.
# For LAN access bind 0.0.0.0 and set SSNOW_API_TOKEN in packaging/docker-compose.yml.
```


## Packaging (Linux)

Prebuilt AppImage: see [Releases](https://github.com/kdsmith18542/SolarSystemNow/releases).

Releases are checksummed and GPG-signed (CI signs when the signing secret is
configured; `release-signing-key.asc` is attached to each release). Verify:

```bash
gpg --import release-signing-key.asc
gpg --verify SHA256SUMS.asc SHA256SUMS
sha256sum -c SHA256SUMS
```

Key fingerprint: `ACA74DC872549C4EC8FF0DF8D248D42F9842E3EA` (see
[SECURITY.md](SECURITY.md)).

```bash
# from the repo root (downloads appimagetool on first run; no FUSE needed)
sh packaging/build_appimage.sh
# produces dist/ssnow (PyInstaller bundle) and packaging/Solar_System_Now-x86_64.AppImage
```

## Hardware / GPU

No CUDA or GPU toolkit is required. Ingest is HTTP/JSON; charts are Qt-painted; the map uses QtWebEngine, which falls back to software rendering if OpenGL is unavailable (`QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu`). MapLibre and a Natural Earth land/border basemap are bundled, so the desktop map works fully offline; the web map falls back to the same outline when the basemap CDN is blocked.

## Data integrity

Missing data renders as missing; nothing is synthesized. Every view shows source attribution and upstream links. Radar is a live overlay only (never stored). CME arrival figures are ballistic SIMULATIONs, always labelled as models — never presented as observations.
