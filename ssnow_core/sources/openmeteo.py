"""Open-Meteo adapter: weather + marine + air quality per location, plus a fixed stratospheric-vortex sampling."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from .base import FetchResult
from ..models import Event, Observation


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

# Fixed stratospheric sampling for a polar-vortex proxy: 10 hPa zonal-wind
# proxy (wind speed) at 60N across three longitudes. No new provider needed.
VORTEX_POINTS = [
    {"name": "vortex-60N-60W", "lat": 60.0, "lon": -60.0, "key": "vortex:60N:315E"},
    {"name": "vortex-60N-0E", "lat": 60.0, "lon": 0.0, "key": "vortex:60N:0E"},
    {"name": "vortex-60N-60E", "lat": 60.0, "lon": 60.0, "key": "vortex:60N:60E"},
]


class OpenMeteoAdapter:
    def __init__(self, spec) -> None:
        self.spec = spec
        self.client_headers = {
            "User-Agent": "ss-now/0.1 (solar-system-now real-data platform)",
            "Accept": "*/*",
        }

    def _get(self, store, client, url: str, source_id: str, params: dict, now) -> bytes:
        response = client.get(url, params=params, headers=self.client_headers, timeout=30.0)
        response.raise_for_status()
        store.save_snapshot(
            source_id,
            str(response.url),
            response.content,
            response.headers.get("content-type", ""),
            status_code=response.status_code,
            fetched_at=now,
        )
        return response.content

    def ingest(self, store, client, now=None) -> FetchResult:
        if now is None:
            now = _utcnow()

        store.begin_attempt(self.spec.id, now)
        locations = store.get_setting("locations", []) or []
        events: list[Event] = []
        observations: list[Observation] = []
        errors: list[str] = []

        for loc in locations:
            key = loc.get("key") or f"{loc.get('lat')},{loc.get('lon')}"
            try:
                payload = self._get(store, client, self.spec.url, f"{self.spec.id}:{key}", {
                    "latitude": loc["lat"],
                    "longitude": loc["lon"],
                    "hourly": "temperature_2m,precipitation_probability,wind_speed_10m",
                    "daily": "sunrise,sunset",
                    "timezone": "auto",
                    "forecast_days": "2",
                }, now)
                ev, obs = self.parse(payload, key, now)
                events.extend(ev)
                observations.extend(obs)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"weather {key}: {exc}")

            try:
                marine = self._get(store, client, MARINE_URL, f"{self.spec.id}:marine:{key}", {
                    "latitude": loc["lat"],
                    "longitude": loc["lon"],
                    "hourly": "wave_height,sea_surface_temperature,ocean_current_velocity",
                    "forecast_days": "2",
                }, now)
                _, mobs = self.parse_marine(marine, key, now)
                observations.extend(mobs)
            except Exception as exc:  # noqa: BLE001
                # Inland locations typically 400 or fail for marine data; do not fail whole location
                errors.append(f"marine {key}: {exc}")

            try:
                aq = self._get(store, client, AIR_QUALITY_URL, f"{self.spec.id}:aq:{key}", {
                    "latitude": loc["lat"],
                    "longitude": loc["lon"],
                    "hourly": "us_aqi,pm2_5",
                    "forecast_days": "2",
                }, now)
                _, aobs = self.parse_air_quality(aq, key, now)
                observations.extend(aobs)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"aq {key}: {exc}")

        for point in VORTEX_POINTS:
            try:
                payload = self._get(store, client, self.spec.url, f"{self.spec.id}:{point['key']}", {
                    "latitude": point["lat"],
                    "longitude": point["lon"],
                    "hourly": "windspeed_10hPa",
                    "forecast_days": "1",
                }, now)
                _, vobs = self.parse_vortex(payload, point["key"], now)
                observations.extend(vobs)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"vortex {point['key']}: {exc}")

        if not events and not observations and errors:
            err_msg = "; ".join(errors[:3])
            store.record_failure(self.spec.id, now, err_msg, self.spec.cadence_seconds)
            return FetchResult(self.spec.id, None, str(self.spec.url), "", [], [], error=err_msg)

        if events:
            store.upsert_events(events)
        if observations:
            store.upsert_observations(observations)
        store.record_success(self.spec.id, now, len(events) + len(observations), self.spec.cadence_seconds)
        return FetchResult(
            self.spec.id, None, str(self.spec.url), "", events, observations
        )

    def parse(self, payload: bytes, key: str, now=None):
        import json

        data = json.loads(payload)
        hourly = data.get("hourly", {}) or {}
        times = hourly.get("time", []) or []
        temperatures = hourly.get("temperature_2m", []) or []
        precipitation = hourly.get("precipitation_probability", []) or []
        wind = hourly.get("wind_speed_10m", []) or []
        observations: list[Observation] = []
        now = now or _utcnow()
        for i, ts_text in enumerate(times):
            ts = datetime.fromisoformat(ts_text.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            temperature = temperatures[i] if i < len(temperatures) else None
            precip = precipitation[i] if i < len(precipitation) else None
            wspd = wind[i] if i < len(wind) else None
            if temperature is not None:
                observations.append(Observation(source="openmeteo", series=f"weather:{key}:temperature_2m", ts=ts, value=float(temperature), unit="°C"))
            if precip is not None:
                observations.append(Observation(source="openmeteo", series=f"weather:{key}:precipitation_probability", ts=ts, value=float(precip), unit="%"))
            if wspd is not None:
                observations.append(Observation(source="openmeteo", series=f"weather:{key}:wind_speed_10m", ts=ts, value=float(wspd), unit="km/h"))
        daily = data.get("daily", {}) or {}
        dtimes = daily.get("time", []) or []
        for i, dtext in enumerate(dtimes):
            ts = datetime.fromisoformat(dtext.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            sunrise = daily.get("sunrise", [])[i] if i < len(daily.get("sunrise", [])) else None
            sunset = daily.get("sunset", [])[i] if i < len(daily.get("sunset", [])) else None
            if sunrise:
                observations.append(Observation(source="openmeteo", series=f"weather:{key}:sunrise", ts=ts, value=_parse_time_to_epoch(sunrise), unit="epoch_seconds"))
            if sunset:
                observations.append(Observation(source="openmeteo", series=f"weather:{key}:sunset", ts=ts, value=_parse_time_to_epoch(sunset), unit="epoch_seconds"))
        return [], observations

    def _parse_hourly_floats(self, payload: bytes, key: str, prefix: str, fields: list[tuple[str, str]], now=None):
        import json

        data = json.loads(payload)
        hourly = data.get("hourly", {}) or {}
        times = hourly.get("time", []) or []
        columns = {name: hourly.get(name, []) or [] for name, _unit in fields}
        observations: list[Observation] = []
        for i, ts_text in enumerate(times):
            ts = datetime.fromisoformat(ts_text.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            for name, unit in fields:
                values = columns[name]
                value = values[i] if i < len(values) else None
                if value is None:
                    continue
                observations.append(Observation(
                    source="openmeteo",
                    series=f"{prefix}:{key}:{name}",
                    ts=ts,
                    value=float(value),
                    unit=unit,
                ))
        return [], observations

    def parse_marine(self, payload: bytes, key: str, now=None):
        return self._parse_hourly_floats(payload, key, "marine", [
            ("wave_height", "m"),
            ("sea_surface_temperature", "°C"),
            ("ocean_current_velocity", "km/h"),
        ], now)

    def parse_air_quality(self, payload: bytes, key: str, now=None):
        return self._parse_hourly_floats(payload, key, "air", [
            ("us_aqi", "USAQI"),
            ("pm2_5", "μg/m³"),
        ], now)

    def parse_vortex(self, payload: bytes, key: str, now=None):
        return self._parse_hourly_floats(payload, key, "strato", [
            ("windspeed_10hPa", "km/h"),
        ], now)


def _parse_time_to_epoch(text: str) -> float:
    from datetime import datetime

    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return parsed.timestamp()
