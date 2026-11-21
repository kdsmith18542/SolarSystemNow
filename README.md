# Solar System Now (ss-now)

Linux desktop platform for reviewing **current and historical real data** about Earth and its neighborhood: earthquakes, volcanoes, storms, wildfires, floods, weather, space weather (Sun/Kp), and the Moon. No fabricated data, no server required, no hosting costs.

## Architecture

- `ssnow_core/` — pure-Python library: adapters, SQLite store, scheduler, CLI. No Qt imports (enforced by test).
- `ssnow_desktop/` — PySide6/Qt GUI for Linux.
- Data sources: USGS, NASA EONET, Open-Meteo, NOAA SWPC, NASA DONKI, NASA SDO imagery, Moon computed with Skyfield (JPL ephemeris).
- Local SQLite database + gzipped raw snapshots; steady-state storage is single-digit GB.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

## Run

```bash
# ingest due sources once
ssnow ingest

# stats
ssnow stats

# launch desktop GUI
ssnow gui
```

Environment overrides: `SSNOW_DATA_DIR`, `SSNOW_CONFIG_DIR`, `SSNOW_CACHE_DIR`.

## Packaging (Linux)

```bash
cd packaging
./build_appimage.sh
# produces dist/ssnow (PyInstaller bundle) and packaging/Solar_System_Now-x86_64.AppImage
```

## Hardware / GPU

No CUDA or GPU toolkit is required. Ingest is HTTP/JSON; charts are Qt-painted; the map uses QtWebEngine, which falls back to software rendering if OpenGL is unavailable (`QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu`).

## Data integrity

Missing data renders as missing; nothing is synthesized. Every view shows source attribution and upstream links. Simulations are deferred to Phase 2 behind a stub interface.
