"""NOAA historical magnetic dip-pole positions (IGRF 1590-2025 + WMM forecast)."""

from __future__ import annotations

from datetime import datetime, timezone

from .base import Adapter, FetchResult
from ..models import Observation


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _wrap_lon(lon: float) -> float:
    return ((lon + 180.0) % 360.0) - 180.0


class GeomagPolesAdapter(Adapter):
    URLS = {
        "north": "https://www.ngdc.noaa.gov/geomag/data/poles/NP.xy",
        "south": "https://www.ngdc.noaa.gov/geomag/data/poles/SP.xy",
        "north_forecast": "https://www.ncei.noaa.gov/sites/default/files/2024-12/WMM2025_NP.txt",
        "south_forecast": "https://www.ncei.noaa.gov/sites/default/files/2024-12/WMM2025_SP.txt",
    }

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
        observations: list[Observation] = []
        errors: list[str] = []
        for key, url in self.URLS.items():
            try:
                response = client.get(url, headers=self.client_headers, timeout=30.0)
                response.raise_for_status()
                store.save_snapshot(
                    f"{self.spec.id}:{key}",
                    str(response.url),
                    response.content,
                    response.headers.get("content-type", ""),
                    status_code=response.status_code,
                    fetched_at=now,
                )
                hemisphere = key.split("_")[0]
                kind = "forecast" if key.endswith("forecast") else "observed"
                observations.extend(self.parse_text(response.content, hemisphere, kind, now))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{key}: {exc}")

        if not observations:
            err_msg = "; ".join(errors[:3]) or "no pole positions parsed"
            store.record_failure(self.spec.id, now, err_msg, self.spec.cadence_seconds)
            return FetchResult(self.spec.id, None, self.spec.url, "", [], [], error=err_msg)

        store.upsert_observations(observations)
        store.record_success(self.spec.id, now, len(observations), self.spec.cadence_seconds)
        return FetchResult(
            self.spec.id,
            None,
            self.spec.url,
            "",
            [],
            observations,
            error=None,
        )

    def parse_text(self, payload: bytes, hemisphere: str, kind: str, now=None) -> list[Observation]:
        text = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else str(payload)
        rows: dict[int, tuple[float, float]] = {}
        for line in text.splitlines():
            parts = line.split()
            if len(parts) < 3:
                continue
            try:
                lon = _wrap_lon(float(parts[0]))
                lat = float(parts[1])
                year = int(float(parts[2]))
            except (TypeError, ValueError):
                continue
            if not (-90.0 <= lat <= 90.0):
                continue
            rows[year] = (lat, lon)

        observations: list[Observation] = []
        for year, (lat, lon) in sorted(rows.items()):
            ts = datetime(year, 1, 1, tzinfo=timezone.utc)
            extra = {
                "pole": hemisphere,
                "year": year,
                "kind": kind,
                "model": "WMM2025" if kind == "forecast" else "IGRF",
            }
            for field, value in (("lat", lat), ("lon", lon)):
                observations.append(
                    Observation(
                        source="geomag_poles",
                        series=f"geomag_pole:{hemisphere}:{field}" if kind == "observed" else f"geomag_pole:{hemisphere}:{field}_forecast",
                        ts=ts,
                        value=value,
                        unit="deg",
                        extra_json=extra,
                    )
                )
        return observations

    def parse_seed(self, payload: bytes, now=None) -> list[Observation]:
        import json

        data = json.loads(payload)
        observations: list[Observation] = []
        for key in ("north", "south", "north_forecast", "south_forecast"):
            text = data.get(key)
            if not text:
                continue
            hemisphere = key.split("_")[0]
            kind = "forecast" if key.endswith("forecast") else "observed"
            observations.extend(self.parse_text(text.encode(), hemisphere, kind, now))
        return observations
