"""NASA DONKI adapters: CME and solar flares."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx

from .base import FetchResult, HttpAdapter
from ..models import Event


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def is_earth_directed(extra: dict) -> bool:
    """Conservative direction check from heliographic source longitude.

    DONKI ``type`` (S/C/O) is a CME morphology class, not a direction flag.
    A wide/halo event or a source near central meridian is treated as
    potentially Earth-directed; limb/backside events are not.
    """
    try:
        half_angle = float(extra.get("half_angle") or 0.0)
    except (TypeError, ValueError):
        half_angle = 0.0
    if half_angle >= 60.0:
        return True
    try:
        stlon = float(extra.get("stlon"))
    except (TypeError, ValueError):
        return False
    return abs(stlon) <= 45.0


def _parse_iso_utc(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class _DonkiAdapter(HttpAdapter):
    def __init__(self, spec) -> None:
        super().__init__(spec)
        self.endpoint_path = spec.url.rstrip("/")
        self._key = "DEMO_KEY"

    def before_request(self, store) -> None:
        self._key = store.get_setting("nasa_api_key") or "DEMO_KEY"

    def build_request(self, now=None):
        end = now or _utcnow()
        start = end - timedelta(days=7)
        params = {
            "startDate": start.date().isoformat(),
            "endDate": end.date().isoformat(),
            "api_key": self._key,
        }
        return "GET", self.endpoint_path, params, {}


class CMEAdapter(_DonkiAdapter):
    def parse(self, payload: bytes, content_type: str, now=None):
        import json

        data = json.loads(payload)
        items = data if isinstance(data, list) else []
        events: list[Event] = []
        now = now or _utcnow()
        for item in items:
            analyses = item.get("cmeAnalyses") or []
            best = next((a for a in analyses if a.get("isMostAccurate")), analyses[0] if analyses else {})
            parsed_time = _parse_iso_utc(item.get("startTime"))
            occurred_at = parsed_time or now
            extra = {
                "time_estimated": parsed_time is None,
                "catalog": item.get("catalog"),
                "activity_id": item.get("activityID"),
                "source_location": item.get("sourceLocation"),
                "active_region": item.get("activeRegionNum"),
                "speed": best.get("speed"),
                "half_angle": best.get("halfAngle"),
                # DONKI CME lat/lon are heliographic (solar disk), never
                # terrestrial coordinates. Keep them separate from Event.
                "stlat": best.get("latitude"),
                "stlon": best.get("longitude"),
                "coordinate_frame": "heliographic",
                "type": best.get("type"),
                "note": best.get("note"),
                "link": best.get("link"),
            }
            events.append(
                Event(
                    id=f"donki:cme:{item.get('activityID')}",
                    source="donki",
                    upstream_id=str(item.get("activityID")),
                    category="cme",
                    title=f"CME {item.get('startTime', '')[:10]}",
                    description=item.get("note") or "",
                    occurred_at=occurred_at,
                    updated_at=_parse_iso_utc(item.get("submissionTime")),
                    latitude=None,
                    longitude=None,
                    depth_km=None,
                    magnitude=float(best.get("speed")) if best.get("speed") is not None else None,
                    magnitude_unit="km/s",
                    url=item.get("link"),
                    ingested_at=now,
                    extra_json=extra,
                )
            )
        return events, []


class GSTAdapter(_DonkiAdapter):
    """DONKI geomagnetic-storm feed (defensive parse; endpoint valid)."""

    def parse(self, payload: bytes, content_type: str, now=None):
        import json

        data = json.loads(payload)
        items = data if isinstance(data, list) else []
        events: list[Event] = []
        now = now or _utcnow()
        for item in items:
            kp_values = []
            for entry in item.get("allKpIndex") or []:
                try:
                    kp_values.append(float(entry.get("kpIndex")))
                except (TypeError, ValueError):
                    continue
            parsed_time = _parse_iso_utc(item.get("startTime"))
            occurred_at = parsed_time or now
            extra = {
                "time_estimated": parsed_time is None,
                "gst_id": item.get("gstID"),
                "kp_values": kp_values,
                "link": item.get("link"),
            }
            events.append(
                Event(
                    id=f"donki:gst:{item.get('gstID') or item.get('startTime')}",
                    source="donki",
                    upstream_id=str(item.get("gstID") or item.get("startTime")),
                    category="geomagnetic_storm",
                    title=f"Geomagnetic storm {str(item.get('startTime', ''))[:10]}",
                    description="",
                    occurred_at=occurred_at,
                    updated_at=None,
                    latitude=None,
                    longitude=None,
                    depth_km=None,
                    magnitude=max(kp_values) if kp_values else None,
                    magnitude_unit="Kp",
                    url=item.get("link"),
                    ingested_at=now,
                    extra_json=extra,
                )
            )
        return events, []


class FlareAdapter(_DonkiAdapter):
    """DONKI solar-flare feed (currently disabled).

    The api.nasa.gov DONKI gateway has no working FLR route (verified 404,
    2026-11-20), so this adapter is registered with enabled=False until the
    upstream route exists. Solar flare activity is covered meanwhile by the
    SWPC GOES X-ray adapter (`swpc_xray`).
    """

    def parse(self, payload: bytes, content_type: str, now=None):
        import json

        data = json.loads(payload)
        items = data if isinstance(data, list) else []
        events: list[Event] = []
        now = now or _utcnow()
        for item in items:
            parsed_time = _parse_iso_utc(item.get("beginTime"))
            occurred_at = parsed_time or now
            extra = {
                "time_estimated": parsed_time is None,
                "class_type": item.get("classType"),
                "source_location": item.get("sourceLocation"),
                "active_region": item.get("activeRegionNum"),
                "peak_time": item.get("peakTime"),
                "link": item.get("link"),
            }
            events.append(
                Event(
                    id=f"donki:flare:{item.get('flareID') or item.get('beginTime')}",
                    source="donki",
                    upstream_id=str(item.get("flareID") or item.get("beginTime")),
                    category="solar_flare",
                    title=f"Solar flare {item.get('classType', '')}",
                    description=item.get("note") or "",
                    occurred_at=occurred_at,
                    updated_at=_parse_iso_utc(item.get("peakTime")),
                    latitude=None,
                    longitude=None,
                    depth_km=None,
                    magnitude=None,
                    magnitude_unit=None,
                    url=item.get("link"),
                    ingested_at=now,
                    extra_json=extra,
                )
            )
        return events, []
