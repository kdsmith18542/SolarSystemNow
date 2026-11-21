"""NASA EONET natural events adapter."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from .base import FetchResult, HttpAdapter
from .geo import geometry_centroid
from ..models import Event

CATEGORY_MAP = {
    "severeStorms": "storm",
    "wildfires": "wildfire",
    "volcanoes": "volcano",
    "floods": "flood",
    "drought": "other",
    "dustHaze": "other",
    "snow": "other",
    "temperatureExtremes": "other",
    "waterColor": "other",
    "manmade": "other",
    "seaLakeIce": "other",
    "earthquakes": "earthquake",
}


class EONETAdapter(HttpAdapter):
    def build_request(self, now=None):
        return "GET", self.spec.url, {"status": "open", "days": "30"}, {}

    def parse(self, payload: bytes, content_type: str, now=None):
        import json

        data = json.loads(payload)
        events_data = data.get("events", []) if isinstance(data, dict) else []
        events: list[Event] = []
        now = now or datetime.now(timezone.utc)
        for item in events_data:
            geometries = item.get("geometry") or []
            latest = geometries[-1] if geometries else {}
            lat, lon = geometry_centroid(latest)
            parsed_time = parse_event_time(latest.get("date")) if geometries else None
            time_estimated = parsed_time is None
            occurred_at = parsed_time or now
            categories = item.get("categories", []) or []
            category = CATEGORY_MAP.get(categories[0].get("id"), "other") if categories else "other"
            extra = {
                "categories": [c.get("id") for c in categories],
                "sources": [s.get("id") for s in item.get("sources", []) or []],
                "magnitude": latest.get("magnitudeValue"),
                "magnitude_unit": latest.get("magnitudeUnit"),
                "geometry_type": latest.get("type"),
                "time_estimated": time_estimated,
            }
            events.append(
                Event(
                    id=f"eonet:{item.get('id')}",
                    source="eonet",
                    upstream_id=str(item.get("id")),
                    category=category,
                    title=item.get("title") or "Event",
                    description=item.get("description"),
                    occurred_at=occurred_at,
                    updated_at=None,
                    latitude=lat,
                    longitude=lon,
                    depth_km=None,
                    magnitude=(
                        float(latest.get("magnitudeValue")) if latest.get("magnitudeValue") is not None else None
                    ),
                    magnitude_unit=latest.get("magnitudeUnit"),
                    url=item.get("link"),
                    raw_ref=None,
                    ingested_at=now,
                    extra_json=extra,
                )
            )
        return events, []

    def persist(self, store, events, observations, now=None):
        filtered = []
        for event in events:
            if event.category == "earthquake":
                match = store.find_nearby_event(
                    "usgs",
                    event.occurred_at,
                    event.latitude or 0.0,
                    event.longitude or 0.0,
                )
                if match is not None:
                    continue
            filtered.append(event)
        super().persist(store, filtered, observations, now)


def parse_event_time(value):
    if value is None:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
