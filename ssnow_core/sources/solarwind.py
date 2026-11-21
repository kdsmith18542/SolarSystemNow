"""SWPC real-time solar-wind + IMF adapters (post-2026 schema).

Replaces the legacy ACE SWEPAM fixed-width text feed
(https://services.swpc.noaa.gov/text/ace-swepam.txt).

New endpoints (SCN 26-21, effective 2026-03-31; old
products/solar-wind/* removed 2026-04-30):
  - https://services.swpc.noaa.gov/json/rtsw/rtsw_wind_1m.json
  - https://services.swpc.noaa.gov/json/rtsw/rtsw_mag_1m.json

Both return JSON arrays of objects with explicit key-value pairs and
numeric values (old header-row + quoted-string shape is also tolerated).
Each row carries ``source`` (spacecraft) and ``active`` (forecaster-selected
primary). Only ``active=true`` rows drive the operational series; the
spacecraft name is preserved in ``extra_json`` provenance.

US public domain (NOAA). Keyless.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .base import HttpAdapter
from ..models import Observation


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


INTERVAL_SECONDS = 300
RETENTION_DAYS = 30


def _downsample(points: list[tuple], series_defs: list[tuple[str, str, dict]]) -> list[Observation]:
    """Bucket 1-min points to 5-min; keep first sample per bucket per series.

    points: list of (ts, {series_suffix: value}, provenance dict).
    series_defs: list of (suffix, unit, static_extra) — value looked up per point.
    """
    # points already sorted; group per series
    observations: list[Observation] = []
    for suffix, unit, static_extra in series_defs:
        seen: set[int] = set()
        for ts, values, prov in points:
            v = values.get(suffix)
            if v is None:
                continue
            bucket = int(ts.timestamp()) // INTERVAL_SECONDS
            if bucket in seen:
                continue
            seen.add(bucket)
            extra = {**static_extra, **prov}
            observations.append(
                Observation(
                    source="swpc",
                    series=f"swpc:{suffix}",
                    ts=ts,
                    value=v,
                    unit=unit,
                    extra_json=extra,
                )
            )
    return observations


class SolarWindAdapter(HttpAdapter):
    """Real-time solar-wind plasma from rtsw_wind_1m.json (active spacecraft)."""

    def build_request(self, now=None):
        return "GET", self.spec.url, None, {}

    def parse(self, payload: bytes, content_type: str, now=None):
        import json

        data = json.loads(payload)
        rows = data if isinstance(data, list) else data.get("data", [])
        points: list[tuple] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if row.get("active") is not True:
                continue
            ts = _parse_iso_utc(row.get("time_tag"))
            if ts is None:
                continue
            values = {
                "solarwind_speed": _fnum(row.get("proton_speed")),
                "solarwind_density": _fnum(row.get("proton_density")),
                "solarwind_temp": _fnum(row.get("proton_temperature")),
            }
            if all(v is None for v in values.values()):
                continue
            prov = {"source": row.get("source"), "spacecraft": row.get("source")}
            points.append((ts, values, prov))
        points.sort(key=lambda p: p[0])
        observations = _downsample(
            points,
            [
                ("solarwind_speed", "km/s", {"instrument": "SWPC RTSW plasma"}),
                ("solarwind_density", "p/cc", {"instrument": "SWPC RTSW plasma"}),
                ("solarwind_temp", "K", {"instrument": "SWPC RTSW plasma"}),
            ],
        )
        return [], observations

    def persist(self, store, events, observations, now=None):
        from datetime import timedelta

        super().persist(store, events, observations, now)
        cutoff = (now or _utcnow()).astimezone(timezone.utc) - timedelta(days=RETENTION_DAYS)
        for series in ("swpc:solarwind_density", "swpc:solarwind_speed", "swpc:solarwind_temp"):
            store.prune_observations_before("swpc", series, cutoff)


class MagAdapter(HttpAdapter):
    """Interplanetary magnetic field (GSM) from rtsw_mag_1m.json.

    The Bz (north-south) component is the primary aurora/storm ingredient
    streamers watch (Bz < -5 nT sustained = alert). Bt is total strength.
    """

    def build_request(self, now=None):
        return "GET", self.spec.url, None, {}

    def parse(self, payload: bytes, content_type: str, now=None):
        import json

        data = json.loads(payload)
        rows = data if isinstance(data, list) else data.get("data", [])
        points: list[tuple] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if row.get("active") is not True:
                continue
            ts = _parse_iso_utc(row.get("time_tag"))
            if ts is None:
                continue
            # Prefer GSM (magnetospheric) components; fall back to GSE.
            values = {
                "imf_bz_gsm": _fnum(row.get("bz_gsm", row.get("bz_gse"))),
                "imf_bt": _fnum(row.get("bt")),
                "imf_by_gsm": _fnum(row.get("by_gsm", row.get("by_gse"))),
                "imf_bx_gsm": _fnum(row.get("bx_gsm", row.get("bx_gse"))),
            }
            if all(v is None for v in values.values()):
                continue
            prov = {"source": row.get("source"), "spacecraft": row.get("source")}
            points.append((ts, values, prov))
        points.sort(key=lambda p: p[0])
        observations = _downsample(
            points,
            [
                ("imf_bz_gsm", "nT", {"component": "Bz GSM"}),
                ("imf_bt", "nT", {"component": "Bt total"}),
                ("imf_by_gsm", "nT", {"component": "By GSM"}),
                ("imf_bx_gsm", "nT", {"component": "Bx GSM"}),
            ],
        )
        return [], observations

    def persist(self, store, events, observations, now=None):
        from datetime import timedelta

        super().persist(store, events, observations, now)
        cutoff = (now or _utcnow()).astimezone(timezone.utc) - timedelta(days=RETENTION_DAYS)
        for series in ("swpc:imf_bz_gsm", "swpc:imf_bt", "swpc:imf_by_gsm", "swpc:imf_bx_gsm"):
            store.prune_observations_before("swpc", series, cutoff)
