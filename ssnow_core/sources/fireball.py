"""JPL CNEOS fireball / bolide adapter (US government sensor detections).

Endpoint: https://ssd-api.jpl.nasa.gov/fireball.api
Params: date-min, date-max, limit. Response: {signature, count, fields, data}
where data rows align with fields:
  ["date", "energy", "impact-e", "lat", "lat-dir", "lon", "lon-dir", "alt", "vel"]

Only date/energy/impact-e are guaranteed; location/alt/vel may be null.
Events carry lat/lon so they render on the Earth map (unlike NEO close
approaches which have no lat/lon).

Category: "fireball". Magnitude = impact energy (kt), unit "kt".
IDs are content-hashed (`fireball:{sha1(date|lat|lon|energy|impact)}[:12]`)
so location-less records sharing a timestamp stay distinct and stable
across refetches — required for notifications, AI labels, and collab refs.

NASA public data, keyless. Fair use: cache, single request per cycle.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from .base import HttpAdapter
from ..models import Event


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _fnum(value) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


class FireballAdapter(HttpAdapter):
    def build_request(self, now=None):
        end = now or _utcnow()
        start = end - timedelta(days=30)
        params = {
            "date-min": start.date().isoformat(),
            "date-max": end.date().isoformat(),
            "limit": "200",
        }
        return "GET", self.spec.url, params, {}

    def parse(self, payload: bytes, content_type: str, now=None):
        import json

        data = json.loads(payload)
        fields = data.get("fields", []) if isinstance(data, dict) else []
        rows = data.get("data", []) if isinstance(data, dict) else []
        idx = {name: i for i, name in enumerate(fields)}
        events: list[Event] = []
        now = now or _utcnow()

        def col(row, name):
            i = idx.get(name)
            if i is None or i >= len(row):
                return None
            return row[i]

        for row in rows:
            parsed_time = _parse_dt(col(row, "date"))
            dt = parsed_time or now
            lat = _fnum(col(row, "lat"))
            lon = _fnum(col(row, "lon"))
            if col(row, "lat-dir") == "S" and lat is not None:
                lat = -abs(lat)
            if col(row, "lon-dir") == "W" and lon is not None:
                lon = -abs(lon)
            energy = _fnum(col(row, "energy"))  # 1e10 joules
            impact = _fnum(col(row, "impact-e"))  # kt
            alt = _fnum(col(row, "alt"))
            vel = _fnum(col(row, "vel"))
            date_s = col(row, "date") or dt.isoformat()
            extra = {
                "time_estimated": parsed_time is None,
                "energy_1e10_j": energy,
                "impact_kt": impact,
                "alt_km": alt,
                "velocity_km_s": vel,
                "sbdb_url": "https://cneos.jpl.nasa.gov/fireballs/",
            }
            title = f"Fireball {date_s} — {impact} kt" if impact else f"Fireball {date_s}"
            uid = hashlib.sha1(f"{date_s}|{lat}|{lon}|{energy}|{impact}".encode()).hexdigest()[:12]
            events.append(
                Event(
                    id=f"fireball:{uid}",
                    source="jpl_fireball",
                    upstream_id=uid,
                    category="fireball",
                    title=title,
                    description="US government sensor bolide detection (CNEOS)",
                    occurred_at=dt,
                    updated_at=None,
                    latitude=lat,
                    longitude=lon,
                    depth_km=None,
                    magnitude=impact,
                    magnitude_unit="kt",
                    url="https://cneos.jpl.nasa.gov/fireballs/",
                    ingested_at=now,
                    extra_json=extra,
                )
            )
        return events, []
