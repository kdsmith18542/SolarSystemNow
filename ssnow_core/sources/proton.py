"""GOES integral proton-flux adapter (radiation-storm / S-scale).

Source: https://services.swpc.noaa.gov/json/goes/primary/integral-protons-1-day.json
Rows: {"time_tag", "satellite", "flux", "energy": ">=10 MeV" | ">=50 MeV" |
">=100 MeV" | ...}. Flux unit is pfu (protons/cm^2/s/sr).

NOAA S-scale thresholds on >=10 MeV: 10 (S1), 100 (S2), 1000 (S3),
10000 (S4), 100000 (S5) pfu. We store raw flux per energy channel and let
views derive the scale — no fabricated alerts.

US public domain (NOAA). Keyless. 5-min downsample, 30-day retention.
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


INTERVAL_SECONDS = 300
RETENTION_DAYS = 30

# Channels we keep (others pass through generically if present).
CHANNELS = (">=10 MeV", ">=50 MeV", ">=100 MeV")


def _series_for(energy: str) -> str:
    tag = energy.replace(">=", "gte").replace(" ", "").replace("MeV", "MeV")
    return f"swpc:proton_flux_{tag}"


class ProtonAdapter(HttpAdapter):
    def build_request(self, now=None):
        return "GET", self.spec.url, None, {}

    def parse(self, payload: bytes, content_type: str, now=None):
        import json

        data = json.loads(payload)
        rows = data if isinstance(data, list) else data.get("data", [])
        # Group per channel, then downsample each.
        by_channel: dict[str, list[tuple]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            ts = _parse_iso_utc(row.get("time_tag"))
            energy = row.get("energy")
            try:
                flux = float(row.get("flux")) if row.get("flux") is not None else None
            except (TypeError, ValueError):
                flux = None
            if ts is None or flux is None or not energy:
                continue
            by_channel.setdefault(str(energy), []).append((ts, flux, row.get("satellite")))

        observations: list[Observation] = []
        for energy, pts in by_channel.items():
            pts.sort(key=lambda p: p[0])
            seen: set[int] = set()
            for ts, flux, sat in pts:
                bucket = int(ts.timestamp()) // INTERVAL_SECONDS
                if bucket in seen:
                    continue
                seen.add(bucket)
                observations.append(
                    Observation(
                        source="swpc",
                        series=_series_for(energy),
                        ts=ts,
                        value=flux,
                        unit="pfu",
                        extra_json={"energy": energy, "satellite": sat},
                    )
                )
        return [], observations

    def persist(self, store, events, observations, now=None):
        from datetime import timedelta

        super().persist(store, events, observations, now)
        cutoff = (now or _utcnow()).astimezone(timezone.utc) - timedelta(days=RETENTION_DAYS)
        for energy in CHANNELS:
            store.prune_observations_before("swpc", _series_for(energy), cutoff)
