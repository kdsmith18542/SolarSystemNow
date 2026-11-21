"""NOAA tides & currents predictions adapter (explicit station IDs).

Station auto-discovery via mdapi ignores lat/lon/radius filters, so stations
are configured explicitly in settings (`tide_stations: [{id, name, lat?, lon?}]`).
Predictions are fetched per station for today+tomorrow and downsampled to hourly.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx

from .base import FetchResult
from ..models import Observation


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso_utc(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00").replace(" ", "T"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class TidesAdapter:
    def __init__(self, spec) -> None:
        self.spec = spec
        self.client_headers = {
            "User-Agent": "ss-now/0.1 (solar-system-now real-data platform)",
            "Accept": "*/*",
        }

    def ingest(self, store, client, now=None) -> FetchResult:
        if now is None:
            now = _utcnow()

        store.begin_attempt(self.spec.id, now)
        stations = store.get_setting("tide_stations", []) or []
        observations: list[Observation] = []
        errors: list[str] = []
        for station in stations:
            try:
                params = {
                    "begin_date": now.strftime("%Y%m%d"),
                    "end_date": (now + timedelta(days=1)).strftime("%Y%m%d"),
                    "station": station["id"],
                    "product": "predictions",
                    "datum": "MLLW",
                    "time_zone": "gmt",
                    "units": "metric",
                    "interval": "hilo",
                    "format": "json",
                }
                response = client.get(self.spec.url, params=params, headers=self.client_headers, timeout=30.0)
                response.raise_for_status()
                store.save_snapshot(
                    f"{self.spec.id}:{station['id']}",
                    str(response.url),
                    response.content,
                    response.headers.get("content-type", ""),
                    status_code=response.status_code,
                    fetched_at=now,
                )
                obs = self.parse(response.content, str(station["id"]), now)
                observations.extend(obs)
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc))
        if errors and not observations:
            err_msg = "; ".join(errors[:3])
            store.record_failure(self.spec.id, now, err_msg, self.spec.cadence_seconds)
            return FetchResult(self.spec.id, None, str(self.spec.url), "", [], [], error=err_msg)

        store.upsert_observations(observations)
        store.record_success(self.spec.id, now, len(observations), self.spec.cadence_seconds)
        return FetchResult(self.spec.id, None, str(self.spec.url), "", [], observations)

    def parse(self, payload: bytes, station_id: str, now=None):
        import json

        data = json.loads(payload)
        items = data.get("predictions", []) if isinstance(data, dict) else []
        observations: list[Observation] = []
        for item in items:
            ts = _parse_iso_utc(item.get("t"))
            try:
                value = float(item.get("v")) if item.get("v") not in (None, "") else None
            except (TypeError, ValueError):
                value = None
            if ts is None or value is None:
                continue
            observations.append(Observation(
                source="tides",
                series=f"tides:{station_id}:height",
                ts=ts,
                value=value,
                unit="m",
                extra_json={"type": item.get("type"), "datum": "MLLW"},
            ))
        return observations
