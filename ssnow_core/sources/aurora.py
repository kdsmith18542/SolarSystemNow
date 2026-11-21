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
OVAL_LON_BINS = 36  # 10-degree longitude bins for the displayed oval boundary
OVAL_REL_THRESHOLD = 0.10  # intensity >= 10% of the hemispheric peak is "oval"


def _oval_boundary(points: list[tuple[float, float, float]], hemisphere: str) -> list[list[float]]:
    """Equatorward auroral-oval boundary as a lon/lat polyline for one hemisphere.

    For each 10-degree longitude bin keep the lowest |lat| where the intensity
    reaches a relative threshold — a compact, display-ready boundary from the
    OVATION grid (no raw grid is stored). Returns [] when nothing qualifies.
    """
    sign = 1.0 if hemisphere == "north" else -1.0
    qualifying: list[tuple[float, float]] = []
    peak = 0.0
    for lon, lat, intensity in points:
        if intensity <= 0 or sign * lat < AURORAL_LAT_BAND:
            continue
        qualifying.append((lon, lat, intensity))
        peak = max(peak, intensity)
    if not qualifying or peak <= 0:
        return []
    threshold = max(1.0, OVAL_REL_THRESHOLD * peak)
    step = 360.0 / OVAL_LON_BINS
    edge_by_bin: dict[int, float] = {}
    for lon, lat, intensity in qualifying:
        if intensity < threshold:
            continue
        b = int((lon + 180.0) // step) % OVAL_LON_BINS
        edge = abs(lat)
        if b not in edge_by_bin or edge < edge_by_bin[b]:
            edge_by_bin[b] = edge
    return [
        [round(-180.0 + step * (b + 0.5), 1), round(sign * edge_by_bin[b], 1)]
        for b in sorted(edge_by_bin)
    ]


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
        triples_parsed: list[tuple[float, float, float]] = []
        for triple in triples:
            try:
                _lon, lat, intensity = float(triple[0]), float(triple[1]), float(triple[2])
            except (TypeError, ValueError, IndexError):
                continue
            triples_parsed.append((_lon, lat, intensity))
            values.append(intensity)
            if abs(lat) >= AURORAL_LAT_BAND and intensity > 0:
                band_values.append(intensity)
                if abs(lat) < min_equatorward:
                    min_equatorward = abs(lat)
        if not values:
            return [], []
        ts = forecast_time or now
        boundary_north = _oval_boundary(triples_parsed, "north")
        boundary_south = _oval_boundary(triples_parsed, "south")
        observations = [
            Observation(source="aurora", series="aurora:intensity_max", ts=ts, value=max(values), unit="ovation",
                        extra_json={"forecast_time": ts.isoformat()}),
            Observation(source="aurora", series="aurora:intensity_mean_band", ts=ts,
                        value=(sum(band_values) / len(band_values)) if band_values else 0.0, unit="ovation",
                        extra_json={"forecast_time": ts.isoformat()}),
            Observation(source="aurora", series="aurora:oval_equatorward_deg", ts=ts,
                        value=min_equatorward if band_values else 90.0, unit="deg_lat",
                        extra_json={
                            "forecast_time": ts.isoformat(),
                            "boundary_north": boundary_north,
                            "boundary_south": boundary_south,
                        }),
        ]
        return [], observations

    def persist(self, store, events, observations, now=None):
        super().persist(store, events, observations, now)
        # Short retention for the ~1 MB raw OVATION grids.
        store.prune_snapshots_for_source(self.spec.id, AURORA_SNAPSHOT_RETENTION_DAYS)
