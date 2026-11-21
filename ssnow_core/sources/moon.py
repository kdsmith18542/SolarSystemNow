"""Moon computation adapter (Skyfield JPL ephemeris, with analytic fallback)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..config import default_ephemeris_path


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Analytic fallback constants (Meeus low-precision).
_SYNODIC_MONTH = 29.530588853
_KNOWN_NEW_MOON = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)  # approximate


def _phase_name(angle_degrees: float) -> str:
    a = angle_degrees % 360.0
    buckets = [
        (0, 22.5, "New Moon"),
        (22.5, 67.5, "Waxing Crescent"),
        (67.5, 112.5, "First Quarter"),
        (112.5, 157.5, "Waxing Gibbous"),
        (157.5, 202.5, "Full Moon"),
        (202.5, 247.5, "Waning Gibbous"),
        (247.5, 292.5, "Last Quarter"),
        (292.5, 337.5, "Waning Crescent"),
    ]
    for low, high, name in buckets:
        if low <= a < high:
            return name
    return "New Moon"


def _fallback_moon(now: datetime) -> dict:
    delta = (now - _KNOWN_NEW_MOON).total_seconds() / 86400.0
    cycle = (delta / _SYNODIC_MONTH) % 1.0
    angle = cycle * 360.0
    illumination = (1.0 - __import__("math").cos(__import__("math").radians(angle))) / 2.0
    return {
        "phase_angle": angle,
        "phase_name": _phase_name(angle),
        "illumination": illumination,
        "distance_km": 384400.0,
        "source": "analytic-fallback",
        "rise_utc": None,
        "set_utc": None,
        "next_rise_utc": None,
        "next_set_utc": None,
    }


class MoonAdapter:
    def __init__(self, spec) -> None:
        self.spec = spec
        self.client_headers = {
            "User-Agent": "ss-now/0.1 (solar-system-now real-data platform)",
            "Accept": "*/*",
        }

    def ingest(self, store, client=None, now=None) -> FetchResult:
        from ..models import Observation

        if now is None:
            now = _utcnow()

        store.begin_attempt(self.spec.id, now)
        try:
            result = self._compute(store, now)
        except Exception as exc:  # noqa: BLE001
            store.record_failure(self.spec.id, now, str(exc), self.spec.cadence_seconds)
            return FetchResult(self.spec.id, None, "", "", [], [], error=str(exc))

        observations = [
            Observation(
                source="moon",
                series="moon:illumination",
                ts=now,
                value=result["illumination"] * 100.0,
                unit="%",
                extra_json={"source": result["source"], "phase_angle": result["phase_angle"], "phase": result["phase_name"]},
            ),
            Observation(
                source="moon",
                series="moon:distance",
                ts=now,
                value=result["distance_km"],
                unit="km",
                extra_json={"source": result["source"]},
            ),
        ]
        store.upsert_observations(observations)
        store.set_setting("moon_state", {
            "phase_angle": result["phase_angle"],
            "illumination": result["illumination"],
            "distance_km": result["distance_km"],
            "phase_name": result["phase_name"],
            "source": result["source"],
            "computed_at": now.isoformat(),
            "rise_utc": result["rise_utc"],
            "set_utc": result["set_utc"],
            "next_rise_utc": result["next_rise_utc"],
            "next_set_utc": result["next_set_utc"],
        })
        store.record_success(self.spec.id, now, len(observations), self.spec.cadence_seconds)
        return FetchResult(self.spec.id, None, "", "", [], observations, assets=0)

    def _compute(self, store, now: datetime) -> dict:
        import math

        try:
            from skyfield.almanac import find_discrete, risings_and_settings
            from skyfield.api import Loader, Topos, load

            eph_path = store.get_setting("ephemeris_path") or _bundled_or_default_ephemeris()
            loader = Loader(str(default_ephemeris_path().parent))
            try:
                eph = load_file_if_available(eph_path, loader)
            except Exception:
                eph = loader("de421.bsp")
            ts = load.timescale()
            t = ts.from_datetime(now)
            earth = eph["earth"]
            moon = eph["moon"]
            sun = eph["sun"]
            astrometric = earth.at(t).observe(moon)
            separation = astrometric.separation_from(earth.at(t).observe(sun)).degrees
            illumination = (1.0 - math.cos(math.radians(separation))) / 2.0
            distance = astrometric.distance().km

            locations = store.get_setting("locations") or []
            location = (locations[0] if locations else None) or store.get_setting("location") or {"lat": 51.5074, "lon": -0.1278, "name": "London"}
            topos = Topos(latitude_degrees=float(location["lat"]), longitude_degrees=float(location["lon"]))
            t0 = ts.from_datetime(now)
            t1 = ts.from_datetime(now + timedelta(days=2))
            times, events_flags = find_discrete(t0, t1, risings_and_settings(eph, moon, topos))
            rise_utc = None
            set_utc = None
            next_rise_utc = None
            next_set_utc = None
            for tt, flag in zip(times, events_flags):
                dt = tt.utc_datetime()
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if flag:
                    if rise_utc is None:
                        rise_utc = dt.isoformat()
                    if next_rise_utc is None and dt > now:
                        next_rise_utc = dt.isoformat()
                else:
                    if set_utc is None:
                        set_utc = dt.isoformat()
                    if next_set_utc is None and dt > now:
                        next_set_utc = dt.isoformat()

            return {
                "phase_angle": float(separation),
                "illumination": float(illumination),
                "distance_km": float(distance),
                "phase_name": _phase_name(float(separation)),
                "source": "skyfield",
                "rise_utc": rise_utc,
                "set_utc": set_utc,
                "next_rise_utc": next_rise_utc,
                "next_set_utc": next_set_utc,
            }
        except Exception:
            return _fallback_moon(now)


def load_file_if_available(path: str, loader):
    from pathlib import Path

    if Path(path).exists():
        from skyfield.api import load_file

        return load_file(path)
    raise FileNotFoundError(path)


def _bundled_or_default_ephemeris() -> str:
    from importlib import resources

    try:
        bundled = resources.files("ssnow_core").joinpath("data/de421.bsp")
        if bundled.is_file():
            return str(bundled)
    except (ModuleNotFoundError, FileNotFoundError):
        pass
    return str(default_ephemeris_path())


class FetchResult:
    def __init__(
        self,
        source_id: str,
        status_code: int | None,
        url: str,
        content_type: str,
        events: list,
        observations: list,
        assets: int = 0,
        error: str | None = None,
    ) -> None:
        self.source_id = source_id
        self.status_code = status_code
        self.url = url
        self.content_type = content_type
        self.events = events
        self.observations = observations
        self.assets = assets
        self.error = error

    @property
    def ok(self) -> bool:
        return self.error is None
