"""FastAPI REST API for ssnow-core data."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from ssnow_core.logging_config import get_logger
from ssnow_core.models import Event
from ssnow_core.redact import redact_secrets
from ssnow_core.scheduler import run_due, utcnow as core_utcnow
from ssnow_core.seed import seed_if_empty
from ssnow_core.sim import get_scenario, list_scenarios
from ssnow_core.sources.registry import all_specs
from ssnow_core.store import Store

app = FastAPI(title="Solar System Now API", version="0.1.3")

logger = get_logger("ssnow_web.api")

# CORS is opt-in: the bundled UI is same-origin (Vite uses its dev proxy).
_cors_origins = [o.strip() for o in (os.environ.get("SSNOW_CORS_ORIGINS") or "").split(",") if o.strip()]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-SSNOW-Token", "Authorization"],
    )

_store: Store | None = None
_subscribers: set[asyncio.Queue] = set()
_ingest_lock = asyncio.Lock()


def _queue_message(q: asyncio.Queue, msg: str) -> None:
    try:
        q.put_nowait(msg)
    except asyncio.QueueFull:
        try:
            q.get_nowait()
            q.put_nowait(msg)
        except (asyncio.QueueEmpty, asyncio.QueueFull):
            pass


async def broadcast_event(data: dict[str, Any]) -> None:
    """Broadcast JSON message to all active SSE subscribers."""
    msg = f"data: {json.dumps(data)}\n\n"
    for q in list(_subscribers):
        _queue_message(q, msg)


def get_store() -> Store:
    global _store
    if _store is None:
        _store = Store()
        # Log the resolved path: SSNOW_DATA_DIR typos create a second, seeded
        # database that looks like data loss (two dirs one character apart).
        logger.info("ssnow-web store opened: %s", _store.db_path)
    return _store


def _require_write_token(request: Request) -> None:
    """Optional write protection for POST endpoints.

    When the server runs with SSNOW_API_TOKEN set (e.g. port-forwarded or
    hosted for other clients), writes and GET `/api/settings` must carry the
    token in either the `X-SSNOW-Token` header or an `Authorization: Bearer
    <token>` header. Unset token (default loopback use) keeps everything open.
    Public upstream GETs stay public.
    """
    expected = (os.environ.get("SSNOW_API_TOKEN") or "").strip()
    if not expected:
        return
    supplied = request.headers.get("x-ssnow-token", "").strip()
    auth = request.headers.get("authorization", "").strip()
    if auth.lower().startswith("bearer "):
        supplied = auth[7:].strip()
    if supplied != expected:
        raise HTTPException(status_code=403, detail="write token required")


@app.on_event("startup")
def _startup() -> None:
    seed_if_empty(get_store())


@app.on_event("shutdown")
def _shutdown() -> None:
    global _store
    if _store is not None:
        _store.close()
        _store = None


def _event_to_dict(event: Event) -> dict[str, Any]:
    return {
        "id": event.id,
        "source": event.source,
        "upstream_id": event.upstream_id,
        "category": event.category,
        "title": event.title,
        "description": event.description,
        "occurred_at": event.occurred_at.isoformat() if event.occurred_at else None,
        "updated_at": event.updated_at.isoformat() if event.updated_at else None,
        "latitude": event.latitude,
        "longitude": event.longitude,
        "depth_km": event.depth_km,
        "magnitude": event.magnitude,
        "magnitude_unit": event.magnitude_unit,
        "url": event.url,
        "raw_ref": event.raw_ref,
        "ingested_at": event.ingested_at.isoformat() if event.ingested_at else None,
        "extra": event.extra_json,
    }


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "ssnow-web"}


@app.get("/api/stats")
def stats() -> dict[str, Any]:
    data = get_store().stats()
    for key in ("snapshots_dir", "assets_dir", "db_path"):
        data.pop(key, None)
    return data


@app.get("/api/events")
def list_events(
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    categories: str | None = Query(default=None),
    min_magnitude: float | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=5000),
    min_lat: float | None = Query(default=None, ge=-90, le=90),
    max_lat: float | None = Query(default=None, ge=-90, le=90),
    min_lon: float | None = Query(default=None, ge=-180, le=180),
    max_lon: float | None = Query(default=None, ge=-180, le=180),
) -> dict[str, Any]:
    store = get_store()
    cat_list = [c.strip() for c in categories.split(",")] if categories else None
    bbox = None
    bbox_values = (min_lat, max_lat, min_lon, max_lon)
    if all(value is not None for value in bbox_values):
        assert min_lat is not None and max_lat is not None and min_lon is not None and max_lon is not None
        if min_lat > max_lat or min_lon > max_lon:
            raise HTTPException(status_code=422, detail="invalid bbox: min must be <= max")
        bbox = (min_lat, max_lat, min_lon, max_lon)
    events = store.query_events(
        start=start,
        end=end,
        categories=cat_list,
        min_magnitude=min_magnitude,
        limit=limit,
        bbox=bbox,
    )
    return {"count": len(events), "events": [_event_to_dict(e) for e in events]}


@app.get("/api/events/{event_id}")
def get_event(event_id: str) -> dict[str, Any]:
    store = get_store()
    event = store.get_event_by_id(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="event not found")
    return _event_to_dict(event)


def _neo_record(event: Event) -> dict[str, Any]:
    ex = event.extra_json or {}

    def _f(v):
        try:
            return float(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None

    ld = _f(ex.get("dist_lunar"))
    if ld is None:
        ld = _f(ex.get("miss_lunar"))
    km = _f(ex.get("dist_km"))
    if km is None:
        km = _f(ex.get("miss_km"))
    if km is None and ld is not None:
        km = ld * 384400.0
    if ld is None and km is not None:
        ld = km / 384400.0
    size = _f(ex.get("diameter_km"))
    if size is None:
        lo, hi = _f(ex.get("diameter_km_min")), _f(ex.get("diameter_km_max"))
        if lo is not None or hi is not None:
            size = ((lo or hi or 0) + (hi or lo or 0)) / 2.0
    is_comet = bool(ex.get("is_comet"))
    kind = ex.get("kind") or ("comet" if is_comet else "asteroid")
    hazardous = bool(ex.get("hazardous") or ex.get("hazardous_candidate"))
    if kind == "sentry":
        try:
            hazardous = float(ex.get("ps_cum", -99)) >= -5.0
        except (TypeError, ValueError):
            hazardous = False
    if is_comet:
        hazardous = False  # comets are not potentially hazardous asteroids
    return {
        "id": event.id,
        "name": (ex.get("fullname") or ex.get("des") or event.title),
        "kind": kind,
        "is_comet": is_comet,
        "hazardous": hazardous,
        "hazardous_candidate": bool(ex.get("hazardous_candidate")),
        "diameter_estimated": bool(ex.get("diameter_estimated")),
        "approach_at": event.occurred_at.isoformat() if event.occurred_at else None,
        "dist_lunar": ld,
        "dist_km": km,
        "velocity_km_s": _f(ex.get("velocity_km_s")),
        "h": _f(ex.get("absolute_magnitude_h")),
        "diameter_km": size,
        "url": event.url,
        "source": event.source,
    }


@app.get("/api/neos")
def list_neos(limit: int = Query(default=200, ge=1, le=2000)) -> dict[str, Any]:
    store = get_store()
    events = store.query_events(categories=["neo"], limit=limit)
    recs = [_neo_record(e) for e in events]
    recs.sort(key=lambda r: (r["dist_lunar"] is None, r["dist_lunar"] if r["dist_lunar"] is not None else 1e9))
    pha = sum(1 for r in recs if r["hazardous"] and not r["is_comet"])
    inside_moon = sum(1 for r in recs if r["dist_lunar"] is not None and r["dist_lunar"] < 1.0)
    comets = sum(1 for r in recs if r["is_comet"])
    return {"count": len(recs), "pha": pha, "inside_moon": inside_moon, "comets": comets, "neos": recs}


@app.get("/api/sources")
def list_sources() -> dict[str, Any]:
    store = get_store()
    states = {state.source_id: state for state in store.all_source_states()}
    rows: list[dict[str, Any]] = []
    for spec in all_specs():
        state = states.get(spec.id)
        rows.append(
            {
                "source_id": spec.id,
                "name": spec.name,
                "domain": spec.domain,
                "attribution": spec.attribution,
                "license": spec.license,
                "cadence_seconds": spec.cadence_seconds,
                "enabled": spec.enabled,
                "last_attempt": state.last_attempt.isoformat() if state and state.last_attempt else None,
                "last_success": state.last_success.isoformat() if state and state.last_success else None,
                "last_error": redact_secrets(state.last_error) if state and state.last_error else None,
                "consecutive_failures": state.consecutive_failures if state else 0,
                "next_due": state.next_due.isoformat() if state and state.next_due else None,
                "records_ingested": state.records_ingested if state else 0,
            }
        )
    rows.sort(key=lambda row: row["source_id"])
    return {"sources": rows}


@app.get("/api/sun/kp")
def sun_kp(
    limit: int = Query(default=120, ge=1, le=10000),
) -> dict[str, Any]:
    store = get_store()
    series = store.get_recent_series("swpc", "swpc:kp", limit=limit)
    return {
        "series": "swpc:kp",
        "unit": "Kp",
        "count": len(series),
        "points": [
            {"ts": obs.ts.isoformat(), "value": obs.value, "estimated": obs.extra_json.get("estimated", False)}
            for obs in series
        ],
    }


@app.get("/api/moon/state")
def moon_state() -> dict[str, Any]:
    store = get_store()
    return store.get_setting("moon_state") or {}


@app.get("/api/weather/now")
def weather_now() -> dict[str, Any]:
    """Latest per-location weather/AQ/marine snapshot in one call.

    Returns one row per configured location (desktop Local Weather card
    parity): temperature, wind, precipitation probability, AQI, PM2.5 and
    marine wave height/SST when available for coastal keys.
    """
    store = get_store()
    locations = [loc for loc in (store.get_setting("locations") or []) if isinstance(loc, dict)]
    rows: list[dict[str, Any]] = []

    def latest(series: str) -> dict[str, Any] | None:
        obs = store.get_latest_observation("openmeteo", series)
        if obs is None:
            return None
        return {"value": obs.value, "unit": obs.unit, "ts": obs.ts.isoformat()}

    for loc in locations:
        key = loc.get("key") or f"{loc.get('lat')},{loc.get('lon')}"
        rows.append(
            {
                "name": loc.get("name", key),
                "temp_c": latest(f"weather:{key}:temperature_2m"),
                "wind_kmh": latest(f"weather:{key}:wind_speed_10m"),
                "precip_pct": latest(f"weather:{key}:precipitation_probability"),
                "aqi": latest(f"air:{key}:us_aqi"),
                "pm25": latest(f"air:{key}:pm2_5"),
                "wave_m": latest(f"marine:{key}:wave_height"),
                "sst_c": latest(f"marine:{key}:sea_surface_temperature"),
            }
        )
    return {"count": len(rows), "locations": rows}


@app.get("/api/weather/{series_id}")
def weather_series(series_id: str, limit: int = Query(default=48, ge=1, le=1000)) -> dict[str, Any]:
    store = get_store()
    series = store.get_recent_series("openmeteo", series_id, limit=limit)
    return {
        "series": series_id,
        "unit": series[0].unit if series else None,
        "count": len(series),
        "points": [{"ts": obs.ts.isoformat(), "value": obs.value} for obs in series],
    }


@app.get("/api/obs")
def observations(
    source: str = Query(),
    series: str = Query(),
    limit: int = Query(default=120, ge=1, le=50000),
    order: Literal["asc", "desc"] = Query(default="asc"),
) -> dict[str, Any]:
    store = get_store()
    rows = store.get_series(source, series, limit=limit, order=order)
    return {
        "source": source,
        "series": series,
        "unit": rows[0].unit if rows else None,
        "count": len(rows),
        "points": [
            {"ts": obs.ts.isoformat(), "value": obs.value, "extra": obs.extra_json}
            for obs in rows
        ],
    }


@app.get("/api/sun/summary")
def sun_summary() -> dict[str, Any]:
    store = get_store()
    def _point(obs):
        return {"value": obs.value, "ts": obs.ts.isoformat()} if obs else None

    kp = store.get_latest_observation("swpc", "swpc:kp")
    kp_fc = store.get_recent_series("swpc", "swpc:kp_forecast", limit=8)
    xray = store.get_latest_observation("swpc", "swpc:xray_flux")
    f107 = store.get_latest_observation("swpc", "swpc:f107")
    aurora = store.get_latest_observation("aurora", "aurora:intensity_max")
    bz = store.get_latest_observation("swpc", "swpc:imf_bz_gsm")
    bt = store.get_latest_observation("swpc", "swpc:imf_bt")
    dst = store.get_latest_observation("swpc", "swpc:dst")
    proton = store.get_latest_observation("swpc", "swpc:proton_flux_gte10MeV")
    proton50 = store.get_latest_observation("swpc", "swpc:proton_flux_gte50MeV")
    proton100 = store.get_latest_observation("swpc", "swpc:proton_flux_gte100MeV")
    wind = store.get_latest_observation("swpc", "swpc:solarwind_speed")
    wind_dens = store.get_latest_observation("swpc", "swpc:solarwind_density")
    aurora_oval = store.get_latest_observation("aurora", "aurora:oval_equatorward_deg")
    aurora_mean = store.get_latest_observation("aurora", "aurora:intensity_mean_band")
    # Magnetic declination is location-dependent: report it for the primary location.
    locations = [loc for loc in (store.get_setting("locations") or []) if isinstance(loc, dict)]
    declination = None
    if locations:
        key = locations[0].get("key") or f"{locations[0].get('lat')},{locations[0].get('lon')}"
        declination = store.get_latest_observation("geomag", f"geomag:{key}:declination")
    def _pole(hemisphere: str) -> dict[str, Any] | None:
        lat = store.get_latest_observation("geomag_poles", f"geomag_pole:{hemisphere}:lat")
        lon = store.get_latest_observation("geomag_poles", f"geomag_pole:{hemisphere}:lon")
        if not lat or not lon:
            return None
        recent_lat = store.get_recent_series("geomag_poles", f"geomag_pole:{hemisphere}:lat", limit=2)
        recent_lon = store.get_recent_series("geomag_poles", f"geomag_pole:{hemisphere}:lon", limit=2)
        previous = None
        drift_km = None
        if len(recent_lat) >= 2 and len(recent_lon) >= 2:
            prev_lat, prev_lon = recent_lat[0].value, recent_lon[0].value
            previous = {"lat": prev_lat, "lon": prev_lon, "year": recent_lat[0].extra_json.get("year")}
            from ssnow_core.sources.geo import haversine_km
            drift_km = round(haversine_km(prev_lat, prev_lon, lat.value, lon.value), 1)
        forecast_lat = store.get_latest_observation("geomag_poles", f"geomag_pole:{hemisphere}:lat_forecast")
        forecast_lon = store.get_latest_observation("geomag_poles", f"geomag_pole:{hemisphere}:lon_forecast")
        forecast = None
        if forecast_lat and forecast_lon:
            forecast = {
                "lat": forecast_lat.value,
                "lon": forecast_lon.value,
                "year": forecast_lat.extra_json.get("year"),
            }
        return {
            "lat": lat.value,
            "lon": lon.value,
            "year": lat.extra_json.get("year"),
            "ts": lat.ts.isoformat(),
            "drift_km": drift_km,
            "previous": previous,
            "forecast": forecast,
        }

    poles = {"north": _pole("north"), "south": _pole("south")}

    ssn = store.get_latest_observation("swpc", "swpc:ssn_observed")
    ssn_pred = store.get_latest_observation("swpc", "swpc:ssn_predicted")
    return {
        "kp": _point(kp),
        "kp_forecast": [{"ts": o.ts.isoformat(), "value": o.value} for o in kp_fc],
        "xray": {**_point(xray), "class": xray.extra_json.get("class")} if xray else None,
        "f107": _point(f107),
        "aurora_max": _point(aurora),
        "bz_gsm": {**_point(bz), "spacecraft": bz.extra_json.get("spacecraft")} if bz else None,
        "bt": _point(bt),
        "dst": _point(dst),
        "proton_gte10": _point(proton),
        "proton_gte50": _point(proton50),
        "proton_gte100": _point(proton100),
        "wind_speed": _point(wind),
        "wind_density": _point(wind_dens),
        "aurora_oval": _point(aurora_oval),
        "aurora_mean": _point(aurora_mean),
        "declination": {**_point(declination), "location": locations[0].get("name")} if declination else None,
        "ssn": _point(ssn),
        "ssn_predicted": _point(ssn_pred),
        "poles": poles,
    }


@app.get("/api/spc/outlooks")
def spc_outlooks(limit: int = Query(default=50, le=500)) -> dict[str, Any]:
    store = get_store()
    events = store.query_events(categories=["severe_outlook"], limit=limit)
    return {"count": len(events), "outlooks": [_event_to_dict(e) for e in events]}


@app.get("/api/fireballs")
def fireballs(limit: int = Query(default=100, le=500)) -> dict[str, Any]:
    store = get_store()
    events = store.query_events(categories=["fireball"], limit=limit)
    return {"count": len(events), "fireballs": [_event_to_dict(e) for e in events]}


@app.get("/api/sun/image")
def sun_image():
    store = get_store()
    path = store.latest_asset("sun_imagery") or store.latest_asset("sun")
    if path and os.path.exists(path):
        return FileResponse(path, media_type="image/jpeg")
    raise HTTPException(status_code=404, detail="No solar image available yet")


SUN_CHANNELS = ("sun_imagery", "sun_sdo193", "sun_sdo304", "sun_hmi", "sun_lasco_c2", "sun_lasco_c3")


@app.get("/api/sun/images")
def sun_images() -> dict[str, Any]:
    store = get_store()
    channels = {}
    for ch in SUN_CHANNELS:
        path = store.latest_asset(ch)
        if path and os.path.exists(path):
            channels[ch] = f"/api/sun/images/{ch}"
    return {"channels": channels}


@app.get("/api/sun/images/{channel}")
def sun_channel_image(channel: str):
    if channel not in SUN_CHANNELS:
        raise HTTPException(status_code=404, detail="unknown solar imagery channel")
    store = get_store()
    path = store.latest_asset(channel)
    if path and os.path.exists(path):
        return FileResponse(path, media_type="image/jpeg")
    raise HTTPException(status_code=404, detail="No image cached for channel yet")


@app.get("/api/stream/live")
async def sse_live(request: Request):
    """Server-Sent Events (SSE) live stream for real-time alerts and ingestion updates."""
    q: asyncio.Queue = asyncio.Queue(maxsize=128)
    _subscribers.add(q)

    # Minimal initial payload: no filesystem paths and no expensive dir walk.
    store = get_store()
    init_data = {
        "type": "connected",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stats": store.counts(),
    }
    _queue_message(q, f"data: {json.dumps(init_data)}\n\n")

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield msg
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            _subscribers.discard(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/ingest")
async def ingest(request: Request) -> dict[str, Any]:
    _require_write_token(request)
    import httpx

    store = get_store()
    now = core_utcnow()

    def _run():
        with httpx.Client() as client:
            return run_due(store, client, now)

    if _ingest_lock.locked():
        raise HTTPException(status_code=409, detail="ingest already running")
    async with _ingest_lock:
        loop = asyncio.get_running_loop()
        reports = await loop.run_in_executor(None, _run)

    summary = {
        "ok": sum(1 for r in reports if r.ok),
        "failed": sum(1 for r in reports if not r.ok),
        "events": sum(len(r.events) for r in reports),
        "observations": sum(len(r.observations) for r in reports),
    }
    result = {
        "timestamp": now.isoformat(),
        "summary": summary,
        "sources": [
            {
                "source_id": r.source_id,
                "ok": r.ok,
                "events": len(r.events),
                "observations": len(r.observations),
                "assets": r.assets,
                "error": redact_secrets(r.error) if r.error else None,
            }
            for r in reports
        ],
    }

    # Broadcast to all live stream listeners
    await broadcast_event(
        {
            "type": "ingest_complete",
            "timestamp": now.isoformat(),
            "summary": summary,
        }
    )

    return result


class LocationModel(BaseModel):
    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    key: str | None = Field(default=None, max_length=64)


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    locations: list[LocationModel] | None = None
    nasa_api_key: str | None = Field(default=None, max_length=200)
    retention_days: int | None = Field(default=None, ge=1, le=3650)


@app.get("/api/settings")
def get_settings(request: Request) -> dict[str, Any]:
    # Configured locations are private when the operator opted into a token.
    _require_write_token(request)
    store = get_store()
    key = store.get_setting("nasa_api_key")
    return {
        "locations": store.get_setting("locations", []),
        "nasa_api_key": bool(key),
        "retention_days": store.get_setting("retention_days", 90),
    }


@app.post("/api/settings")
def set_settings(body: SettingsUpdate, request: Request) -> dict[str, Any]:
    _require_write_token(request)
    store = get_store()
    values: dict[str, Any] = {}
    if body.locations is not None:
        values["locations"] = [loc.model_dump() for loc in body.locations]
    if "nasa_api_key" in body.model_fields_set:
        values["nasa_api_key"] = body.nasa_api_key or None
    if body.retention_days is not None:
        values["retention_days"] = body.retention_days
    if values:
        store.set_settings(values)
    return {"ok": True}


@app.get("/api/sim/scenarios")
def list_sim_scenarios() -> dict[str, Any]:
    scenarios = []
    for meta in list_scenarios():
        scenarios.append(
            {
                "id": meta.id,
                "title": meta.title,
                "description": meta.description,
                "citation": meta.citation,
                "params": [
                    {
                        "id": p.id,
                        "label": p.label,
                        "type": p.type,
                        "unit": p.unit,
                        "default": p.default,
                        "min": p.min,
                        "max": p.max,
                        "options": p.options,
                    }
                    for p in meta.params
                ],
                "output_labels": meta.output_labels,
            }
        )
    return {"scenarios": scenarios}


@app.post("/api/sim/run")
def run_sim(body: dict[str, Any], request: Request) -> dict[str, Any]:
    _require_write_token(request)
    sim_id = body.get("id")
    params = body.get("params", {}) or {}
    cls = get_scenario(sim_id)
    if cls is None:
        raise HTTPException(status_code=404, detail=f"unknown simulation id: {sim_id}")
    for p in cls.meta.params:
        params.setdefault(p.id, p.default)
    scenario = cls()
    result = scenario.run(params)
    return {"scenario": sim_id, "simulation": True, "result": result}


@app.get("/api/sim/cme-watch")
def cme_watch() -> dict[str, Any]:
    """Auto-fed CME arrival estimate: latest directed DONKI CME with a real
    measured speed + latest measured GOES flux run through the flare_arrival
    SIMULATION. Labelled model output, never an observation."""
    from ssnow_core.sim.flare import flare_class_from_flux
    from ssnow_core.sources.donki import is_earth_directed

    store = get_store()
    cmes = store.query_events(categories=["cme"], limit=20)
    if not cmes:
        return {"available": False, "reason": "No CME in window"}
    candidates: list[tuple[Event, float]] = []
    for event in cmes:
        ex = event.extra_json or {}
        if not is_earth_directed(ex):
            continue
        try:
            speed = float(ex.get("speed"))
        except (TypeError, ValueError):
            continue
        if speed <= 0:
            continue
        candidates.append((event, speed))
    if not candidates:
        return {
            "available": False,
            "reason": "No Earth-directed CME with a measured speed in window",
        }
    best, speed = max(candidates, key=lambda pair: pair[1])
    xray = store.get_latest_observation("swpc", "swpc:xray_flux")
    if xray is None:
        return {"available": False, "reason": "No measured X-ray flux for storm proxy"}
    flare = flare_class_from_flux(float(xray.value))
    if flare is None:
        return {"available": False, "reason": "X-ray flux below A-class floor"}
    letter, subclass = flare
    now = core_utcnow()
    age_hours = 0.0
    if best.occurred_at is not None:
        age_hours = max(0.0, (now - best.occurred_at).total_seconds() / 3600.0)
    cls = get_scenario("flare_arrival")
    assert cls is not None
    result = cls().run(
        {
            "cme_speed_km_s": speed,
            "distance_au": 1.0,
            "flare_class": letter,
            "flare_subclass": subclass,
            "elapsed_hours": min(age_hours, 240.0),
        }
    )
    total = float(result.get("total_travel_hours") or 0.0)
    if age_hours > total * 1.25 and total > 0:
        return {
            "available": False,
            "reason": "CME travel window already elapsed (run Sim explorer with custom inputs)",
            "cme_id": best.id,
            "cme_time": best.occurred_at.isoformat() if best.occurred_at else None,
            "cme_age_hours": age_hours,
        }
    return {
        "available": True,
        "simulation": True,
        "cme_id": best.id,
        "cme_time": best.occurred_at.isoformat() if best.occurred_at else None,
        "cme_age_hours": age_hours,
        "cme_speed_km_s": speed,
        "flare_class": letter,
        "flare_subclass": subclass,
        "flare_flux_w_m2": float(xray.value),
        "xray_time": xray.ts.isoformat(),
        "result": result,
    }


# ---- Static file serving (built React front-end) ----

_BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = (_BASE_DIR / ".." / "static").resolve()
if not STATIC_DIR.exists():
    STATIC_DIR = (_BASE_DIR / "dist").resolve()
INDEX_HTML = STATIC_DIR / "index.html"
_ASSETS_ROOT = (STATIC_DIR / "assets").resolve()


@app.get("/assets/{path:path}")
def assets(path: str):
    try:
        target = (_ASSETS_ROOT / path).resolve()
    except (OSError, ValueError):
        raise HTTPException(status_code=404, detail="asset not found")
    if not target.is_relative_to(_ASSETS_ROOT) or not target.is_file():
        raise HTTPException(status_code=404, detail="asset not found")
    return FileResponse(target)


@app.get("/favicon.svg")
def favicon():
    path = STATIC_DIR / "favicon.svg"
    if path.exists():
        return FileResponse(path, media_type="image/svg+xml")
    raise HTTPException(status_code=404, detail="favicon not found")


@app.get("/")
def root():
    if INDEX_HTML.exists():
        return FileResponse(INDEX_HTML)
    return {"detail": "front-end not built; run `npm run build` in ssnow_web/"}


@app.get("/{full_path:path}")
def spa(full_path: str):
    if full_path.startswith("api"):
        raise HTTPException(status_code=404)
    if INDEX_HTML.exists():
        return FileResponse(INDEX_HTML)
    return {"detail": "front-end not built; run `npm run build` in ssnow_web/"}

