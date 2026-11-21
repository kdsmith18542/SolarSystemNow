"""WMM magnetic-declination adapter (per saved location, daily)."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from .base import FetchResult
from ..models import Observation


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class GeomagAdapter:
    def __init__(self, spec) -> None:
        self.spec = spec
        self.client_headers = {
            "User-Agent": "ss-now/0.1 (solar-system-now real-data platform)",
            "Accept": "*/*",
        }

    def _api_key(self, store) -> str:
        return store.get_setting("geomag_api_key") or "zNEw7"

    def ingest(self, store, client, now=None) -> FetchResult:
        if now is None:
            now = _utcnow()

        store.begin_attempt(self.spec.id, now)
        try:
            locations = store.get_setting("locations") or []
            observations: list[Observation] = []
            for loc in locations:
                params = {
                    "lat1": loc["lat"],
                    "lon1": loc["lon"],
                    "key": self._api_key(store),
                    "resultFormat": "json",
                }
                response = client.get(self.spec.url, params=params, headers=self.client_headers, timeout=30.0)
                response.raise_for_status()
                store.save_snapshot(
                    f"{self.spec.id}:{loc.get('key') or loc['lat']},{loc.get('lon')}",
                    str(response.url),
                    response.content,
                    response.headers.get("content-type", ""),
                    status_code=response.status_code,
                    fetched_at=now,
                )
                obs = self.parse(response.content, loc.get("key") or f"{loc['lat']},{loc['lon']}", now)
                observations.extend(obs)
        except Exception as exc:  # noqa: BLE001
            store.record_failure(self.spec.id, now, str(exc), self.spec.cadence_seconds)
            return FetchResult(self.spec.id, None, str(self.spec.url), "", [], [], error=str(exc))

        store.upsert_observations(observations)
        store.record_success(self.spec.id, now, len(observations), self.spec.cadence_seconds)
        return FetchResult(self.spec.id, None, str(self.spec.url), "", [], observations)

    def parse(self, payload: bytes, key: str, now=None):
        import json

        data = json.loads(payload)
        results = data.get("result", []) if isinstance(data, dict) else []
        observations: list[Observation] = []
        now = now or _utcnow()
        for item in results:
            declination = item.get("declination")
            if declination is None:
                continue
            observations.append(
                Observation(
                    source="geomag",
                    series=f"geomag:{key}:declination",
                    ts=now,
                    value=float(declination),
                    unit="deg",
                    extra_json={
                        "model": data.get("model"),
                        "declination_sv": item.get("declination_sv"),
                        "uncertainty": item.get("declination_uncertainty"),
                    },
                )
            )
        return observations
