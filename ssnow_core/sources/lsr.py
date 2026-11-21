"""Iowa State IEM Local Storm Report (LSR) adapter — observed ground truth.

Endpoint: https://mesonet.agron.iastate.edu/geojson/lsr.geojson
Params: sts / ets (UTC `YYYY-MM-DDTHH:MMZ`). We pull the trailing 24 h.
Response: FeatureCollection of Point features with properties:
  {wfo, type, typetext, magf, magnitude, unit, city, county, state, valid,
  source, qualifier, product_id, remark}

Type codes include T (tornado), H (hail), G/N (wind gusts). Magnitude units
vary (IN for hail, MPH/KT for wind) and are preserved verbatim.

Category: "storm" with kind="lsr" so reports ride the existing Storm layer
and Events filter — no new category needed. Free for any lawful purpose
including commercial (IEM terms), attribution preserved per-event.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from .base import HttpAdapter
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


def _fnum(value) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


class LSRAdapter(HttpAdapter):
    def build_request(self, now=None):
        end = now or _utcnow()
        start = end - timedelta(hours=24)
        fmt = lambda dt: dt.strftime("%Y-%m-%dT%H:%MZ")  # noqa: E731
        return "GET", self.spec.url, {"sts": fmt(start), "ets": fmt(end)}, {}

    def parse(self, payload: bytes, content_type: str, now=None):
        import json

        data = json.loads(payload)
        features = data.get("features", []) if isinstance(data, dict) else []
        events: list[Event] = []
        now = now or _utcnow()
        for feat in features:
            props = feat.get("properties") or {}
            geom = feat.get("geometry") or {}
            coords = geom.get("coordinates") or []
            lon = _fnum(coords[0]) if len(coords) > 0 else _fnum(props.get("lon"))
            lat = _fnum(coords[1]) if len(coords) > 1 else _fnum(props.get("lat"))
            occurred_at = _parse_iso_utc(props.get("valid")) or now
            typetext = props.get("typetext") or props.get("type") or "storm report"
            mag = _fnum(props.get("magf"))
            if mag is None:
                mag = _fnum(props.get("magnitude"))
            unit = props.get("unit")
            city = props.get("city") or ""
            state = props.get("state") or ""
            where = f"{city}, {state}".strip(", ") or props.get("county") or ""
            mag_txt = f" {mag}{(' ' + unit) if unit else ''}" if mag is not None else ""
            extra = {
                "kind": "lsr",
                "lsr_type": props.get("type"),
                "typetext": typetext,
                "magnitude_raw": props.get("magnitude"),
                "wfo": props.get("wfo"),
                "county": props.get("county"),
                "source": props.get("source"),
                "qualifier": props.get("qualifier"),
                "product_id": props.get("product_id"),
                "remark": props.get("remark"),
            }
            events.append(
                Event(
                    id=f"lsr:{props.get('product_id') or hashlib.sha1(f'{occurred_at.isoformat()}|{lat}|{lon}|{typetext}|{mag}'.encode()).hexdigest()[:12]}",
                    source="iem_lsr",
                    upstream_id=str(props.get("product_id") or occurred_at.isoformat()),
                    category="storm",
                    title=f"LSR {typetext}{mag_txt} — {where}".strip(" —"),
                    description=f"Local storm report via {props.get('wfo')} ({props.get('source')})",
                    occurred_at=occurred_at,
                    updated_at=None,
                    latitude=lat,
                    longitude=lon,
                    depth_km=None,
                    magnitude=mag,
                    magnitude_unit=unit,
                    url="https://mesonet.agron.iastate.edu/nws/",
                    ingested_at=now,
                    extra_json=extra,
                )
            )
        return events, []
