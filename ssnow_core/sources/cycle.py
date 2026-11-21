"""SWPC solar-cycle indices adapter (observed + predicted sunspot / F10.7).

Endpoints (keyless, US public domain):
  - https://services.swpc.noaa.gov/json/solar-cycle/observed-solar-cycle-indices.json
    monthly {"time-tag": "2026-05", "ssn", "smoothed_ssn", "f10.7",
    "smoothed_f10.7", ...} — sentinel -1.0 means missing.
  - https://services.swpc.noaa.gov/json/solar-cycle/predicted-solar-cycle.json
    monthly {"time-tag", "predicted_ssn", "high_ssn", "low_ssn",
    "predicted_f10.7", ...}

Series: swpc:ssn_observed, swpc:f107_observed, swpc:ssn_predicted,
swpc:f107_predicted (monthly points; long retention — 11-year context).
"""

from __future__ import annotations

from datetime import datetime, timezone

from .base import FetchResult
from ..models import Observation


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_month(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value).strip()[:7], "%Y-%m").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _fnum(value) -> float | None:
    try:
        if value is None:
            return None
        v = float(value)
        return None if v == -1.0 else v
    except (TypeError, ValueError):
        return None


OBS_URL = "https://services.swpc.noaa.gov/json/solar-cycle/observed-solar-cycle-indices.json"
PRED_URL = "https://services.swpc.noaa.gov/json/solar-cycle/predicted-solar-cycle.json"


class SolarCycleAdapter:
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
        for url, kind in ((OBS_URL, "obs"), (PRED_URL, "pred")):
            try:
                response = client.get(url, headers=self.client_headers, timeout=30.0)
                response.raise_for_status()
                store.save_snapshot(
                    f"{self.spec.id}:{kind}", str(response.url), response.content,
                    response.headers.get("content-type", ""), status_code=response.status_code, fetched_at=now,
                )
                observations.extend(self._parse_payload(response.content, kind))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{kind}: {exc}")
        if not observations and errors:
            msg = "; ".join(errors[:2])
            store.record_failure(self.spec.id, now, msg, self.spec.cadence_seconds)
            return FetchResult(self.spec.id, None, OBS_URL, "", [], [], error=msg)
        store.upsert_observations(observations)
        store.record_success(self.spec.id, now, len(observations), self.spec.cadence_seconds)
        return FetchResult(self.spec.id, 200, OBS_URL, "application/json", [], observations)

    def parse(self, payload: bytes, content_type: str, now=None):
        return [], self._parse_payload(payload, "obs")

    def _parse_payload(self, payload: bytes, kind: str) -> list[Observation]:
        import json

        data = json.loads(payload)
        rows = data if isinstance(data, list) else data.get("data", [])
        out: list[Observation] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            ts = _parse_month(row.get("time-tag"))
            if ts is None:
                continue
            if kind == "obs":
                pairs = (("ssn", "swpc:ssn_observed", "SSN"), ("f10.7", "swpc:f107_observed", "sfu"))
            else:
                pairs = (("predicted_ssn", "swpc:ssn_predicted", "SSN"), ("predicted_f10.7", "swpc:f107_predicted", "sfu"))
            for key, series, unit in pairs:
                v = _fnum(row.get(key))
                if v is None:
                    continue
                extra = {"cycle_kind": kind}
                if kind == "pred":
                    extra.update({"high_ssn": row.get("high_ssn"), "low_ssn": row.get("low_ssn")})
                out.append(Observation(source="swpc", series=series, ts=ts, value=v, unit=unit, extra_json=extra))
        return out
