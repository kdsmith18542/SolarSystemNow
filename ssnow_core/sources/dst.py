"""Kyoto Dst index adapter (disturbance storm time).

Source: https://services.swpc.noaa.gov/products/kyoto-dst.json
New (2026-03-31) object-array format:
  [{"time_tag": "2026-11-21T01:00:00", "dst": 7}, ...]
Numeric values (old quoted-string shape tolerated). Hourly cadence.

Dst <= -50 nT = moderate storm, <= -100 nT = intense. Views derive the
verdict from the stored series; the adapter stores raw values only.

US public domain (NOAA/SWPC mirror of Kyoto WDC). Keyless.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .base import HttpAdapter
from ..models import Observation


def _parse_iso_utc(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class DstAdapter(HttpAdapter):
    def build_request(self, now=None):
        return "GET", self.spec.url, None, {}

    def parse(self, payload: bytes, content_type: str, now=None):
        import json

        data = json.loads(payload)
        rows = data if isinstance(data, list) else data.get("data", [])
        observations: list[Observation] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            ts = _parse_iso_utc(row.get("time_tag"))
            try:
                dst = float(row.get("dst")) if row.get("dst") is not None else None
            except (TypeError, ValueError):
                dst = None
            if ts is None or dst is None:
                continue
            observations.append(
                Observation(
                    source="swpc",
                    series="swpc:dst",
                    ts=ts,
                    value=dst,
                    unit="nT",
                    extra_json={"index": "Dst"},
                )
            )
        return [], observations
