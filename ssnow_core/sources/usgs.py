"""USGS earthquake feed adapter."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from .base import FetchResult, HttpAdapter
from ..models import Event


class USGSAdapter(HttpAdapter):
    def build_request(self, now=None):
        return "GET", self.spec.url, None, {}

    def parse(self, payload: bytes, content_type: str, now=None):
        import json

        data = json.loads(payload)
        features = data.get("features", []) if isinstance(data, dict) else []
        events: list[Event] = []
        for feature in features:
            props = feature.get("properties", {}) or {}
            geometry = feature.get("geometry") or {}
            coordinates = geometry.get("coordinates") or []
            magnitude = props.get("mag")
            time_ms = props.get("time")
            updated_ms = props.get("updated")
            occurred_at = None
            if isinstance(time_ms, (int, float)):
                occurred_at = datetime.fromtimestamp(time_ms / 1000.0, tz=timezone.utc)
            updated_at = None
            if isinstance(updated_ms, (int, float)):
                updated_at = datetime.fromtimestamp(updated_ms / 1000.0, tz=timezone.utc)
            extra = {
                "sig": props.get("sig"),
                "mag_type": props.get("magType"),
                "status": props.get("status"),
                "tsunami": props.get("tsunami"),
                "alert": props.get("alert"),
                "felt": props.get("felt"),
                "net": props.get("net"),
                "code": props.get("code"),
                "place": props.get("place"),
            }
            events.append(
                Event(
                    id=f"usgs:{feature.get('id')}",
                    source="usgs",
                    upstream_id=str(feature.get("id")),
                    category="earthquake",
                    title=props.get("title") or props.get("place") or "Earthquake",
                    description=props.get("place"),
                    occurred_at=occurred_at,
                    updated_at=updated_at,
                    latitude=float(coordinates[1]) if len(coordinates) > 1 else None,
                    longitude=float(coordinates[0]) if len(coordinates) > 0 else None,
                    depth_km=float(coordinates[2]) if len(coordinates) > 2 else None,
                    magnitude=float(magnitude) if magnitude is not None else None,
                    magnitude_unit="M",
                    url=props.get("url"),
                    extra_json=extra,
                    ingested_at=now or datetime.now(timezone.utc),
                )
            )
        return events, []
