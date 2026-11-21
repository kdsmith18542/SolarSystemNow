"""NOAA OVATION aurora adapter (derived summary, not the raw grid).

The OVATION JSON is a ~65k-point global [lon, lat, intensity] grid (~1 MB
per fetch). Storing the raw grid every cycle would blow the storage budget,
so this adapter stores compact derived observations (hemispheric max/mean,
auroral-oval extent) and keeps raw snapshots on a short 7-day retention.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from .base import FetchResult, HttpAdapter
from ..models import Observation


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


AURORA_SNAPSHOT_RETENTION_DAYS = 7
AURORAL_LAT_BAND = 15.0  # |lat| above this counts as auroral zone


class AuroraAdapter(HttpAdapter):
    def build_request(self, now=None):
        return "GET", self.spec.url, None, {}

    def parse(self, payload: bytes, content_type: str, now=None):
        import json

        data = json.loads(payload)
        triples = data.get("coordinates", []) if isinstance(data, dict) else []
        now = now or _utcnow()
        forecast_time = None
        try:
            from datetime import datetime as _dt

            forecast_time = _dt.fromisoformat(str(data.get("Forecast Time", "")).replace("Z", "+00:00"))
            if forecast_time.tzinfo is None:
                forecast_time = forecast_time.replace(tzinfo=timezone.utc)
        except (ValueError, AttributeError):
            forecast_time = now

        values = []
        band_values = []
        min_equatorward = 90.0
        for triple in triples:
            try:
                _lon, lat, intensity = float(triple[0]), float(triple[1]), float(triple[2])
            except (TypeError, ValueError, IndexError):
                continue
            values.append(intensity)
            if abs(lat) >= AURORAL_LAT_BAND and intensity > 0:
                band_values.append(intensity)
                if abs(lat) < min_equatorward:
                    min_equatorward = abs(lat)
        if not values:
            return [], []
        ts = forecast_time or now
        observations = [
            Observation(source="aurora", series="aurora:intensity_max", ts=ts, value=max(values), unit="ovation",
                        extra_json={"forecast_time": ts.isoformat()}),
            Observation(source="aurora", series="aurora:intensity_mean_band", ts=ts,
                        value=(sum(band_values) / len(band_values)) if band_values else 0.0, unit="ovation",
                        extra_json={"forecast_time": ts.isoformat()}),
            Observation(source="aurora", series="aurora:oval_equatorward_deg", ts=ts,
                        value=min_equatorward if band_values else 90.0, unit="deg_lat",
                        extra_json={"forecast_time": ts.isoformat()}),
        ]
        return [], observations

    def persist(self, store, events, observations, now=None):
        super().persist(store, events, observations, now)
        # Short retention for the ~1 MB raw OVATION grids.
        store.prune_snapshots_for_source(self.spec.id, AURORA_SNAPSHOT_RETENTION_DAYS)
