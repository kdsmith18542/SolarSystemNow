"""NOAA SPC convective outlook adapter (Day 1-3 severe weather polygons).

Static GeoJSON files (keyless, US public domain):
  https://www.spc.noaa.gov/products/outlook/day1otlk_cat.lyr.geojson
  ... day1otlk_{torn,wind,hail}.lyr.geojson
  ... day2otlk_cat.lyr.geojson, day3otlk_cat.lyr.geojson

Each feature has properties {DN, LABEL, LABEL2, VALID_ISO, EXPIRE_ISO,
ISSUE_ISO, FORECASTER} and MultiPolygon geometry. DN scale:
  2 TSTM, 3 MRGL, 4 SLGT, 5 ENH, 6 MDT, 8 HIGH.

Category: "severe_outlook". Magnitude = DN, unit "SPC".
Centroid of the first polygon is stored as lat/lon (point compatibility);
the full polygon is kept in extra_json.geometry for map overlays.
Watches (tornado/severe-thunderstorm) already arrive via the NWS alerts feed.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from .base import FetchResult
from ..models import Event


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso_utc(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


BASE = "https://www.spc.noaa.gov/products/outlook"
# (day, hazard) pairs: hazard matches the filename infix.
TARGETS: list[tuple[str, str]] = [
    ("day1", "cat"),
    ("day1", "torn"),
    ("day1", "wind"),
    ("day1", "hail"),
    ("day2", "cat"),
    ("day3", "cat"),
]


def _stable_id(day: str, hazard: str, props: dict, coords) -> str:
    """Deterministic ID: hash of canonical content, not feature order.

    SPC may reorder polygons between issuances; an index-based ID would
    churn (breaking notifications, AI labels, cross-client references).
    """
    try:
        ring = coords[0][0] if isinstance(coords[0][0][0], (list, tuple)) else coords[0]
        flat = ",".join(f"{round(float(p[0]), 3)},{round(float(p[1]), 3)}" for p in ring[:64])
    except (TypeError, IndexError, ValueError):
        flat = ""
    key = f"{day}|{hazard}|{props.get('VALID', '')}|{props.get('LABEL', '')}|{flat}"
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def _centroid_of_coords(coords) -> tuple[float | None, float | None]:
    """Centroid of first exterior ring of first polygon (Multi)Polygon."""
    try:
        if not coords:
            return None, None
        # MultiPolygon: coords[0][0] is first exterior ring; Polygon: coords[0].
        ring = coords[0][0] if isinstance(coords[0][0][0], (list, tuple)) else coords[0]
        lons = [p[0] for p in ring if len(p) > 1]
        lats = [p[1] for p in ring if len(p) > 1]
        if not lons or not lats:
            return None, None
        return sum(lats) / len(lats), sum(lons) / len(lons)
    except (TypeError, IndexError):
        return None, None


class SPCOutlookAdapter:
    def __init__(self, spec) -> None:
        self.spec = spec
        self.client_headers = {
            "User-Agent": "ss-now/0.1 (solar-system-now real-data platform)",
            "Accept": "*/*",
        }

    def ingest(self, store, client, now=None) -> FetchResult:
        if now is None:
            now = _utcnow()
        store.begin_attempt(self.spec.id, now)
        events: list[Event] = []
        errors: list[str] = []
        for day, hazard in TARGETS:
            url = f"{BASE}/{day}otlk_{hazard}.lyr.geojson"
            try:
                response = client.get(url, headers=self.client_headers, timeout=30.0)
                response.raise_for_status()
                store.save_snapshot(
                    f"{self.spec.id}:{day}:{hazard}",
                    str(response.url),
                    response.content,
                    response.headers.get("content-type", ""),
                    status_code=response.status_code,
                    fetched_at=now,
                )
                evs, _ = self.parse_feature_collection(response.content, day, hazard, now)
                events.extend(evs)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{day}/{hazard}: {exc}")
        if not events and errors:
            msg = "; ".join(errors[:3])
            store.record_failure(self.spec.id, now, msg, self.spec.cadence_seconds)
            return FetchResult(self.spec.id, None, BASE, "", [], [], error=msg)
        store.upsert_events(events)
        store.record_success(self.spec.id, now, len(events), self.spec.cadence_seconds)
        return FetchResult(self.spec.id, 200, BASE, "application/geo+json", events, [])

    def parse(self, payload: bytes, content_type: str, now=None):
        # Single-payload compatibility (tests): treated as day1/cat.
        return self.parse_feature_collection(payload, "day1", "cat", now)

    def parse_feature_collection(self, payload: bytes, day: str, hazard: str, now=None):
        import json

        data = json.loads(payload)
        features = data.get("features", []) if isinstance(data, dict) else []
        events: list[Event] = []
        now = now or _utcnow()
        for i, feat in enumerate(features):
            props = feat.get("properties") or {}
            geom = feat.get("geometry") or {}
            coords = geom.get("coordinates")
            lat, lon = _centroid_of_coords(coords)
            try:
                dn = int(props.get("DN")) if props.get("DN") is not None else None
            except (TypeError, ValueError):
                dn = None
            parsed_time = _parse_iso_utc(props.get("ISSUE_ISO"))
            occurred_at = parsed_time or now
            label = props.get("LABEL") or "TSTM"
            label2 = props.get("LABEL2") or ""
            title = f"SPC {day} {hazard} {label} ({label2})".strip()
            extra = {
                "time_estimated": parsed_time is None,
                "day": day,
                "hazard": hazard,
                "dn": dn,
                "label": label,
                "label2": label2,
                "valid_iso": props.get("VALID_ISO"),
                "expire_iso": props.get("EXPIRE_ISO"),
                "issue_iso": props.get("ISSUE_ISO"),
                "forecaster": props.get("FORECASTER"),
                "geometry": geom,
            }
            events.append(
                Event(
                    id=f"spc:{day}:{hazard}:{_stable_id(day, hazard, props, coords)}",
                    source="spc_outlook",
                    upstream_id=f"{day}:{hazard}:{label}:{_stable_id(day, hazard, props, coords)}",
                    category="severe_outlook",
                    title=title,
                    description=f"SPC convective outlook {day} {hazard} {label} — {label2}".strip(),
                    occurred_at=occurred_at,
                    updated_at=_parse_iso_utc(props.get("EXPIRE_ISO")),
                    latitude=lat,
                    longitude=lon,
                    depth_km=None,
                    magnitude=float(dn) if dn is not None else None,
                    magnitude_unit="SPC",
                    url="https://www.spc.noaa.gov/products/outlook/",
                    ingested_at=now,
                    extra_json=extra,
                )
            )
        return events, []
