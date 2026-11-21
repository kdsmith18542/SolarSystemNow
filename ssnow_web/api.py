"""FastAPI REST API for ssnow-core data."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any
import os

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from ssnow_core.models import Event
from ssnow_core.scheduler import run_due, utcnow as core_utcnow
from ssnow_core.seed import seed_if_empty
from ssnow_core.sim import get_scenario, list_scenarios
from ssnow_core.store import Store
from ssnow_core.sources.registry import all_specs, spec_for

app = FastAPI(title="Solar System Now API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_store: Store | None = None
_subscribers: set[asyncio.Queue] = set()


async def broadcast_event(data: dict[str, Any]) -> None:
    """Broadcast JSON message to all active SSE subscribers."""
    msg = f"data: {json.dumps(data)}\n\n"
    for q in list(_subscribers):
        try:
            q.put_nowait(msg)
        except Exception:
            pass


def get_store() -> Store:
    global _store
    if _store is None:
        _store = Store()
    return _store


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
    return get_store().stats()


@app.get("/api/events")
def list_events(
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    categories: str | None = Query(default=None),
    min_magnitude: float | None = Query(default=None),
    limit: int = Query(default=500, le=5000),
) -> dict[str, Any]:
    store = get_store()
    start_dt = datetime.fromisoformat(start) if start else None
    end_dt = datetime.fromisoformat(end) if end else None
    cat_list = [c.strip() for c in categories.split(",")] if categories else None
    events = store.query_events(
        start=start_dt,
        end=end_dt,
        categories=cat_list,
        min_magnitude=min_magnitude,
        limit=limit,
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
    kind = ex.get("kind") or ("comet" if ex.get("is_comet") else "asteroid")
    hazardous = bool(ex.get("hazardous") or ex.get("hazardous_candidate"))
    if kind == "sentry":
        try:
            hazardous = float(ex.get("ps_cum", -99)) >= -5.0
        except (TypeError, ValueError):
            hazardous = False
    return {
        "id": event.id,
        "name": (ex.get("fullname") or ex.get("des") or event.title),
        "kind": kind,
        "is_comet": bool(ex.get("is_comet")),
        "hazardous": hazardous,
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
def list_neos(limit: int = Query(default=200, le=2000)) -> dict[str, Any]:
    store = get_store()
    events = store.query_events(categories=["neo"], limit=limit)
    recs = [_neo_record(e) for e in events]
    recs.sort(key=lambda r: (r["dist_lunar"] is None, r["dist_lunar"] or 1e9))
    pha = sum(1 for r in recs if r["hazardous"])
    inside_moon = sum(1 for r in recs if r["dist_lunar"] is not None and r["dist_lunar"] < 1.0)
    comets = sum(1 for r in recs if r["is_comet"])
    return {"count": len(recs), "pha": pha, "inside_moon": inside_moon, "comets": comets, "neos": recs}


@app.get("/api/sources")
def list_sources() -> dict[str, Any]:
    store = get_store()
    states = store.all_source_states()
    specs = {s.id: s for s in all_specs()}
    return {
        "sources": [
            {
                "source_id": state.source_id,
                "name": specs[state.source_id].name if state.source_id in specs else state.source_id,
                "domain": specs[state.source_id].domain if state.source_id in specs else "—",
                "attribution": specs[state.source_id].attribution if state.source_id in specs else "—",
                "license": specs[state.source_id].license if state.source_id in specs else "—",
                "cadence_seconds": specs[state.source_id].cadence_seconds if state.source_id in specs else None,
                "enabled": specs[state.source_id].enabled if state.source_id in specs else False,
                "last_attempt": state.last_attempt.isoformat() if state.last_attempt else None,
                "last_success": state.last_success.isoformat() if state.last_success else None,
                "last_error": state.last_error,
                "consecutive_failures": state.consecutive_failures,
                "next_due": state.next_due.isoformat() if state.next_due else None,
                "records_ingested": state.records_ingested,
            }
            for state in states
        ]
    }


@app.get("/api/sun/kp")
def sun_kp(
    limit: int = Query(default=120, le=10000),
) -> dict[str, Any]:
    store = get_store()
    series = store.get_series("swpc", "swpc:kp", limit=limit)
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


@app.get("/api/weather/{series_id}")
def weather_series(series_id: str, limit: int = Query(default=48, le=1000)) -> dict[str, Any]:
    store = get_store()
    series = store.get_series("openmeteo", series_id, limit=limit)
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
    limit: int = Query(default=120, le=10000),
) -> dict[str, Any]:
    store = get_store()
    rows = store.get_series(source, series, limit=limit)
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
    kp = store.latest_observations("swpc", "swpc:kp")
    kp_fc = store.get_series("swpc", "swpc:kp_forecast", limit=8)
    xray = store.get_series("swpc", "swpc:xray_flux", limit=1)
    f107 = store.get_series("swpc", "swpc:f107", limit=1)
    aurora = store.get_series("aurora", "aurora:intensity_max", limit=1)
    bz = store.get_series("swpc", "swpc:imf_bz_gsm", limit=1)
    bt = store.get_series("swpc", "swpc:imf_bt", limit=1)
    dst = store.get_series("swpc", "swpc:dst", limit=1)
    proton = store.get_series("swpc", "swpc:proton_flux_gte10MeV", limit=1)
    ssn = store.get_series("swpc", "swpc:ssn_observed", limit=1)
    ssn_pred = store.get_series("swpc", "swpc:ssn_predicted", limit=1)
    return {
        "kp": {"value": kp[0].value, "ts": kp[0].ts.isoformat()} if kp else None,
        "kp_forecast": [{"ts": o.ts.isoformat(), "value": o.value} for o in kp_fc],
        "xray": {
            "value": xray[-1].value,
            "ts": xray[-1].ts.isoformat(),
            "class": xray[-1].extra_json.get("class"),
        } if xray else None,
        "f107": {"value": f107[-1].value, "ts": f107[-1].ts.isoformat()} if f107 else None,
        "aurora_max": {"value": aurora[0].value, "ts": aurora[0].ts.isoformat()} if aurora else None,
        "bz_gsm": {"value": bz[-1].value, "ts": bz[-1].ts.isoformat(), "spacecraft": bz[-1].extra_json.get("spacecraft")} if bz else None,
        "bt": {"value": bt[-1].value, "ts": bt[-1].ts.isoformat()} if bt else None,
        "dst": {"value": dst[-1].value, "ts": dst[-1].ts.isoformat()} if dst else None,
        "proton_gte10": {"value": proton[-1].value, "ts": proton[-1].ts.isoformat()} if proton else None,
        "ssn": {"value": ssn[-1].value, "ts": ssn[-1].ts.isoformat()} if ssn else None,
        "ssn_predicted": {"value": ssn_pred[-1].value, "ts": ssn_pred[-1].ts.isoformat()} if ssn_pred else None,
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
    q: asyncio.Queue = asyncio.Queue()
    _subscribers.add(q)

    # Initial connection payload
    store = get_store()
    init_data = {
        "type": "connected",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stats": store.stats(),
    }
    q.put_nowait(f"data: {json.dumps(init_data)}\n\n")

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
async def ingest() -> dict[str, Any]:
    import httpx

    store = get_store()
    now = core_utcnow()

    def _run():
        with httpx.Client() as client:
            return run_due(store, client, now)

    loop = asyncio.get_running_loop()
    reports = await loop.run_in_executor(None, _run)

    result = {
        "timestamp": now.isoformat(),
        "sources": [
            {
                "source_id": r.source_id,
                "ok": r.ok,
                "events": len(r.events),
                "observations": len(r.observations),
                "assets": r.assets,
                "error": r.error,
            }
            for r in reports
        ],
    }

    # Broadcast to all live stream listeners
    await broadcast_event({
        "type": "ingest_complete",
        "timestamp": now.isoformat(),
        "summary": {
            "ok": sum(1 for r in reports if r.ok),
            "failed": sum(1 for r in reports if not r.ok),
            "events": sum(len(r.events) for r in reports),
            "observations": sum(len(r.observations) for r in reports),
        },
    })

    return result


@app.get("/api/settings")
def get_settings() -> dict[str, Any]:
    store = get_store()
    key = store.get_setting("nasa_api_key")
    return {
        "locations": store.get_setting("locations", []),
        "tide_stations": store.get_setting("tide_stations", []),
        "nasa_api_key": bool(key),
        "retention_days": store.get_setting("retention_days", 90),
    }


@app.post("/api/settings")
def set_settings(body: dict[str, Any]) -> dict[str, Any]:
    store = get_store()
    if "locations" in body:
        store.set_setting("locations", body["locations"])
    if "tide_stations" in body:
        store.set_setting("tide_stations", body["tide_stations"])
    if "nasa_api_key" in body:
        store.set_setting("nasa_api_key", body["nasa_api_key"] or None)
    if "retention_days" in body:
        store.set_setting("retention_days", int(body["retention_days"]))
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
def run_sim(body: dict[str, Any]) -> dict[str, Any]:
    sim_id = body.get("id")
    params = body.get("params", {}) or {}
    cls = get_scenario(sim_id)
    if cls is None:
        raise HTTPException(status_code=404, detail=f"unknown simulation id: {sim_id}")
    for p in cls.meta.params:
        params.setdefault(p.id, p.default)
    scenario = cls()
    result = scenario.run(params)
    return {"scenario": sim_id, "result": result}


@app.get("/api/sim/cme-watch")
def cme_watch() -> dict[str, Any]:
    """Auto-fed CME arrival estimate: latest DONKI CME speed + latest X-ray
    flare class run through the flare_arrival SIMULATION. Labelled model
    output (ballistic constant-speed assumption), NOT an observation."""
    store = get_store()
    cmes = store.query_events(categories=["cme"], limit=5)
    if not cmes:
        return {"available": False, "reason": "No CME in window"}
    # Prefer the fastest recent Earth-directed candidate.
    def _score(e):
        ex = e.extra_json or {}
        try:
            speed = float(ex.get("speed") or 0)
        except (TypeError, ValueError):
            speed = 0.0
        directed = ex.get("type") in ("S", "C") or (ex.get("half_angle") or 0) >= 60
        return (directed, speed)

    best = max(cmes, key=_score)
    ex = best.extra_json or {}
    try:
        speed = float(ex.get("speed") or 500.0)
    except (TypeError, ValueError):
        speed = 500.0
    xray = store.get_series("swpc", "swpc:xray_flux", limit=1)
    letter = (xray[-1].extra_json.get("class", "C") if xray else "C")[:1].upper()
    if letter not in ("A", "B", "C", "M", "X"):
        letter = "C"
    cls = get_scenario("flare_arrival")
    assert cls is not None
    result = cls().run({"cme_speed_km_s": speed, "distance_au": 1.0, "flare_class": letter, "flare_subclass": 5.0})
    return {
        "available": True,
        "simulation": True,
        "cme_id": best.id,
        "cme_time": best.occurred_at.isoformat() if best.occurred_at else None,
        "cme_speed_km_s": speed,
        "flare_class": letter,
        "result": result,
    }


# ---- Static file serving (built React front-end) ----

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(_BASE_DIR, "..", "static")
if not os.path.exists(STATIC_DIR):
    STATIC_DIR = os.path.join(_BASE_DIR, "dist")
INDEX_HTML = os.path.join(STATIC_DIR, "index.html")


@app.get("/assets/{path:path}")
def assets(path: str):
    return FileResponse(os.path.join(STATIC_DIR, "assets", path))


@app.get("/")
def root():
    if os.path.exists(INDEX_HTML):
        return FileResponse(INDEX_HTML)
    return {"detail": "front-end not built; run `npm run build` in ssnow_web/"}


@app.get("/{full_path:path}")
def spa(full_path: str):
    if full_path.startswith("api"):
        raise HTTPException(status_code=404)
    if os.path.exists(INDEX_HTML):
        return FileResponse(INDEX_HTML)
    return {"detail": "front-end not built; run `npm run build` in ssnow_web/"}

