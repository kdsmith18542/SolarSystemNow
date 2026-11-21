"""NWS active alerts adapter (US + territories, keyless GeoJSON)."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from .base import FetchResult, HttpAdapter
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


def _centroid(coordinates) -> tuple[float | None, float | None]:
    # GeoJSON Polygon: coordinates[0] is the exterior ring.
    try:
        if not coordinates:
            return None, None
        ring = coordinates[0] if isinstance(coordinates[0][0], (list, tuple)) else coordinates
        lons = [p[0] for p in ring if len(p) > 1]
        lats = [p[1] for p in ring if len(p) > 1]
        if not lons or not lats:
            return None, None
        return sum(lats) / len(lats), sum(lons) / len(lons)
    except (TypeError, IndexError):
        return None, None


class NWSAlertsAdapter(HttpAdapter):
    def build_request(self, now=None):
        return "GET", self.spec.url, {"status": "actual", "message_type": "alert"}, {}

    def parse(self, payload: bytes, content_type: str, now=None):
        import json

        data = json.loads(payload)
        features = data.get("features", []) if isinstance(data, dict) else []
        events: list[Event] = []
        now = now or _utcnow()
        for feature in features:
            props = feature.get("properties") or {}
            geometry = feature.get("geometry") or {}
            lat, lon = None, None
            if geometry.get("type") == "Point":
                coords = geometry.get("coordinates") or []
                if len(coords) > 1:
                    lon, lat = float(coords[0]), float(coords[1])
            elif geometry.get("type") == "Polygon":
                lat, lon = _centroid(geometry.get("coordinates"))
            occurred_at = (
                _parse_iso_utc(props.get("onset"))
                or _parse_iso_utc(props.get("sent"))
                or _parse_iso_utc(props.get("effective"))
                or now
            )
            severity = props.get("severity")
            event_name = props.get("event") or "Weather alert"
            extra = {
                "nws_id": props.get("id"),
                "area": props.get("areaDesc"),
                "severity": severity,
                "certainty": props.get("certainty"),
                "urgency": props.get("urgency"),
                "sender": props.get("senderName"),
                "instruction": props.get("instruction"),
                "expires": props.get("expires"),
            }
            events.append(
                Event(
                    id=f"nws:{props.get('id')}",
                    source="nws",
                    upstream_id=str(props.get("id")),
                    category="weather_alert",
                    title=props.get("headline") or event_name,
                    description=props.get("description"),
                    occurred_at=occurred_at,
                    updated_at=_parse_iso_utc(props.get("sent")),
                    latitude=lat,
                    longitude=lon,
                    depth_km=None,
                    magnitude=None,
                    magnitude_unit=None,
                    url=props.get("@id"),
                    ingested_at=now,
                    extra_json=extra,
                )
            )
        return events, []
