"""NOAA SWPC adapters: planetary K-index and alerts."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from .base import FetchResult, HttpAdapter
from ..models import Event, Observation


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


class KpAdapter(HttpAdapter):
    def build_request(self, now=None):
        return "GET", self.spec.url, None, {}

    def parse(self, payload: bytes, content_type: str, now=None):
        import json

        data = json.loads(payload)
        rows = data if isinstance(data, list) else data.get("data", [])
        observations: list[Observation] = []
        now = now or _utcnow()
        for row in rows:
            ts = _parse_iso_utc(row.get("time_tag"))
            if ts is None:
                continue
            if row.get("observed") == "predicted":
                observations.append(
                    Observation(
                        source="swpc",
                        series="swpc:kp_forecast",
                        ts=ts,
                        value=float(row.get("kp", 0.0)),
                        unit="Kp",
                        extra_json={"noaa_scale": row.get("noaa_scale")},
                    )
                )
                continue
            kp = row.get("kp_index")
            if kp is None:
                kp = row.get("kp")
            estimated = row.get("estimated_kp")
            value = kp if kp is not None else estimated
            if value is None:
                continue
            observations.append(
                Observation(
                    source="swpc",
                    series="swpc:kp",
                    ts=ts,
                    value=float(value),
                    unit="Kp",
                    extra_json={"estimated": estimated is not None and kp is None},
                )
            )
        return [], observations


class AlertsAdapter(HttpAdapter):
    def build_request(self, now=None):
        return "GET", self.spec.url, None, {}

    def parse(self, payload: bytes, content_type: str, now=None):
        import json

        data = json.loads(payload)
        items = data if isinstance(data, list) else data.get("alerts", [])
        events: list[Event] = []
        now = now or _utcnow()
        for item in items:
            message = item.get("message") or ""
            title = str(message).splitlines()[0] if message else "Space Weather Alert"
            issued = _parse_iso_utc(item.get("issue_datetime"))
            occurred_at = issued or now
            product = str(item.get("product_id") or "")
            serial = str(item.get("serial_number") or "").strip()
            if serial:
                key = f"{product or 'alert'}:{serial}"
            elif issued is not None:
                key = f"{product or 'alert'}:{issued.isoformat()}"
            else:
                import hashlib

                key = f"{product or 'alert'}:{hashlib.sha1(message.encode('utf-8')).hexdigest()[:12]}"
            events.append(
                Event(
                    id=f"swpc:alert:{key}",
                    source="swpc",
                    upstream_id=key,
                    category="space_weather_alert",
                    title=title,
                    description=message,
                    occurred_at=occurred_at,
                    updated_at=None,
                    latitude=None,
                    longitude=None,
                    depth_km=None,
                    magnitude=None,
                    magnitude_unit=None,
                    url="https://www.swpc.noaa.gov/",
                    ingested_at=now,
                    extra_json={
                        "time_estimated": issued is None,
                        "product_id": item.get("product_id"),
                        "serial_number": item.get("serial_number"),
                        "issue_datetime": item.get("issue_datetime"),
                        "regions": item.get("regions"),
                    },
                )
            )
        return events, []


class KpForecastAdapter(KpAdapter):
    """3-day Kp forecast (same parser; keeps predicted rows only)."""

    def parse(self, payload: bytes, content_type: str, now=None):
        import json

        data = json.loads(payload)
        rows = data if isinstance(data, list) else data.get("data", [])
        observations: list[Observation] = []
        for row in rows:
            if row.get("observed") != "predicted":
                continue
            ts = _parse_iso_utc(row.get("time_tag"))
            if ts is None or row.get("kp") is None:
                continue
            observations.append(
                Observation(
                    source="swpc",
                    series="swpc:kp_forecast",
                    ts=ts,
                    value=float(row.get("kp")),
                    unit="Kp",
                    extra_json={"noaa_scale": row.get("noaa_scale")},
                )
            )
        return [], observations


# GOES soft X-ray flux bands: the 0.1-0.8 nm band defines flare class
# (A/B/C/M/X = 1e-8 ... 1e-4 W/m^2). 1-minute cadence is downsampled to
# 5 minutes on ingest; older than 30 days is pruned.
XRAY_BAND = "0.1-0.8nm"
XRAY_INTERVAL_SECONDS = 300
XRAY_RETENTION_DAYS = 30


def _flare_class(flux_w_m2: float) -> str:
    if flux_w_m2 >= 1e-4:
        return "X"
    if flux_w_m2 >= 1e-5:
        return "M"
    if flux_w_m2 >= 1e-6:
        return "C"
    if flux_w_m2 >= 1e-7:
        return "B"
    return "A"


class XrayAdapter(HttpAdapter):
    def build_request(self, now=None):
        return "GET", self.spec.url, None, {}

    def parse(self, payload: bytes, content_type: str, now=None):
        import json

        data = json.loads(payload)
        rows = data if isinstance(data, list) else data.get("data", [])
        points: list[tuple] = []
        for row in rows:
            if row.get("energy") != XRAY_BAND:
                continue
            ts = _parse_iso_utc(row.get("time_tag"))
            flux = row.get("flux")
            if ts is None or flux is None:
                continue
            points.append((ts, float(flux), int(row.get("satellite") or 0)))
        points.sort(key=lambda p: p[0])

        # 5-minute downsampling: keep the first sample per bucket.
        observations: list[Observation] = []
        seen_buckets: set[int] = set()
        for ts, flux, satellite in points:
            bucket = int(ts.timestamp()) // XRAY_INTERVAL_SECONDS
            if bucket in seen_buckets:
                continue
            seen_buckets.add(bucket)
            observations.append(
                Observation(
                    source="swpc",
                    series="swpc:xray_flux",
                    ts=ts,
                    value=flux,
                    unit="W/m^2",
                    extra_json={"band": XRAY_BAND, "satellite": satellite, "class": _flare_class(flux)},
                )
            )
        return [], observations

    def persist(self, store, events, observations, now=None):
        from datetime import timedelta, timezone

        super().persist(store, events, observations, now)
        cutoff = (now or _utcnow()).astimezone(timezone.utc) - timedelta(days=XRAY_RETENTION_DAYS)
        store.prune_observations_before("swpc", "swpc:xray_flux", cutoff)


class F107Adapter(HttpAdapter):
    def build_request(self, now=None):
        return "GET", self.spec.url, None, {}

    def parse(self, payload: bytes, content_type: str, now=None):
        import json

        data = json.loads(payload)
        rows = data if isinstance(data, list) else data.get("data", [])
        observations: list[Observation] = []
        for row in rows:
            ts = _parse_iso_utc(row.get("time_tag"))
            flux = row.get("flux")
            if ts is None or flux is None:
                continue
            observations.append(
                Observation(
                    source="swpc",
                    series="swpc:f107",
                    ts=ts,
                    value=float(flux),
                    unit="sfu",
                    extra_json={
                        "frequency_mhz": row.get("frequency"),
                        "reporting_schedule": row.get("reporting_schedule"),
                        "ninety_day_mean": row.get("ninety_day_mean"),
                    },
                )
            )
        return [], observations
