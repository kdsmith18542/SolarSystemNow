"""NWS active alerts adapter (US + territories, keyless GeoJSON)."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from .base import FetchResult, HttpAdapter
from .geo import geometry_centroid
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
            lat, lon = geometry_centroid(geometry)
            parsed_time = (
                _parse_iso_utc(props.get("onset"))
                or _parse_iso_utc(props.get("sent"))
                or _parse_iso_utc(props.get("effective"))
            )
            occurred_at = parsed_time or now
            severity = props.get("severity")
            event_name = props.get("event") or "Weather alert"
            extra = {
                "time_estimated": parsed_time is None,
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
