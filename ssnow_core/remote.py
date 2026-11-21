"""HTTP-backed read store for Remote Server mode (desktop).

`RemoteStore` duck-types the read subset of `Store` used by desktop views,
fetching from a running `ssnow-web` instance instead of local SQLite:

- events      -> GET /api/events, /api/events/{id}
- observations-> GET /api/obs (order=desc for latest)
- settings    -> GET /api/settings + /api/moon/state, POST /api/settings
- sources     -> GET /api/sources (converted to SourceState)
- stats       -> GET /api/stats
- imagery     -> GET /api/sun/image{s/...} (downloaded to a local temp cache)
- notifications -> in-memory only (no server persistence yet)

Writes other than the four settings keys are not supported and raise
`RemoteReadOnlyError`. No Qt imports here (core invariant).
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from .logging_config import get_logger
from .models import Event, Observation, SourceState

logger = get_logger("remote")

WRITABLE_SETTINGS = ("locations", "tide_stations", "nasa_api_key", "retention_days")


class RemoteReadOnlyError(RuntimeError):
    """Raised when a local-only write is attempted in remote mode."""


class RemoteStore:
    """Read-oriented store backed by a remote ssnow-web instance."""

    is_remote = True

    def __init__(self, base_url: str, timeout: float = 30.0, client: httpx.Client | None = None, token: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.token = (token or "").strip() or None
        self._client = client or httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            headers={"User-Agent": "ss-now/0.1 (remote-desktop)"},
        )
        self._owns_client = client is None
        self.db_path = f"{self.base_url} (remote server)"
        self._asset_cache = Path(tempfile.gettempdir()) / "ssnow-remote-assets"
        self._asset_cache.mkdir(parents=True, exist_ok=True)
        self._asset_ts: dict[str, float] = {}
        self._notifs: dict[str, dict[str, Any]] = {}
        self._delivered: set[str] = set()
        # Read-through cache: periodic prefetch runs on a worker thread so
        # view refreshes are cache hits instead of UI-thread HTTP stalls.
        self.cache_ttl = 300.0
        self._cache: dict[tuple[str, str], tuple[float, Any]] = {}
        self._cache_lock = threading.RLock()

    # -- internal ---------------------------------------------------------

    def _auth_headers(self) -> dict[str, str] | None:
        return {"X-SSNOW-Token": self.token} if self.token else None

    @staticmethod
    def _cache_key(path: str, params: dict[str, Any] | None) -> tuple[str, str]:
        if not params:
            return path, ""

        def _normalize(key: str, value: Any) -> Any:
            # Round time windows to 5-minute buckets so a prefetch and the
            # following view refresh share a key despite second-level drift.
            if key in ("start", "end") and isinstance(value, str):
                try:
                    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    return f"bucket:{int(dt.timestamp() // 300)}"
                except ValueError:
                    return value
            return value

        normalized = {key: _normalize(key, value) for key, value in params.items()}
        return path, json.dumps(normalized, sort_keys=True, default=str)

    def invalidate_cache(self) -> None:
        with self._cache_lock:
            self._cache.clear()

    def _get(self, path: str, params: dict[str, Any] | None = None, *, use_cache: bool = True) -> Any:
        key = self._cache_key(path, params)
        if use_cache and self.cache_ttl > 0:
            with self._cache_lock:
                entry = self._cache.get(key)
            if entry is not None and time.time() - entry[0] <= self.cache_ttl:
                return entry[1]
        try:
            resp = self._client.get(
                path, params=params, headers=self._auth_headers(), timeout=self.timeout
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Remote GET %s failed: %s", path, exc)
            raise
        with self._cache_lock:
            self._cache[key] = (time.time(), data)
        return data

    def prefetch(self) -> dict[str, int]:
        """Warm the read cache off the UI thread (called by a QThread).

        Failures are isolated per endpoint: stale cache entries stay usable.
        """
        calls: list[tuple[str, dict[str, Any] | None]] = []

        def add(path: str, params: dict[str, Any] | None = None) -> None:
            calls.append((path, params))

        now = datetime.now(timezone.utc)
        add("/api/settings")
        add("/api/moon/state")
        add("/api/sources")
        add("/api/stats")
        add("/api/sun/summary")
        add("/api/sun/images")
        add("/api/sun/kp", {"limit": 120})
        add("/api/sun/kp", {"limit": 200})
        add("/api/neos", {"limit": 200})
        add("/api/weather/now")
        add("/api/spc/outlooks", {"limit": 50})
        add("/api/fireballs", {"limit": 100})
        add("/api/sim/cme-watch")

        # Events used by Now / Events / Map / alerts.
        add("/api/events", {"limit": 1, "categories": "earthquake"})
        add("/api/events", {"limit": 20, "categories": "cme"})
        add("/api/events", {"limit": 500, "categories": "neo"})
        add(
            "/api/events",
            {
                "limit": 20,
                "categories": "earthquake",
                "min_magnitude": 6.0,
                "start": (now - timedelta(hours=6)).isoformat(),
            },
        )
        for days in (7, 30):
            add(
                "/api/events",
                {
                    "limit": 500,
                    "start": (now - timedelta(days=days)).isoformat(),
                    "end": now.isoformat(),
                },
            )

        # Exact latest series used by Now / Sun / streamer banner / alerts.
        for series in (
            "swpc:kp",
            "swpc:xray_flux",
            "swpc:f107",
            "swpc:solarwind_speed",
            "swpc:solarwind_density",
            "swpc:imf_bz_gsm",
            "swpc:imf_bt",
            "swpc:proton_flux_gte10MeV",
            "swpc:proton_flux_gte50MeV",
            "swpc:proton_flux_gte100MeV",
            "swpc:dst",
            "swpc:ssn_observed",
            "swpc:ssn_predicted",
        ):
            add("/api/obs", {"source": "swpc", "series": series, "limit": 1, "order": "desc"})
        for limit in (8, 24):
            add("/api/obs", {"source": "swpc", "series": "swpc:kp_forecast", "limit": limit, "order": "desc"})
        for series in ("aurora:intensity_max", "aurora:oval_equatorward_deg"):
            add("/api/obs", {"source": "aurora", "series": series, "limit": 1, "order": "desc"})

        try:
            locations = [loc for loc in (self.get_setting("locations") or []) if isinstance(loc, dict)]
        except Exception:  # noqa: BLE001
            locations = []
        if locations:
            key = locations[0].get("key") or f"{locations[0].get('lat')},{locations[0].get('lon')}"
            for series in (
                f"weather:{key}:temperature_2m",
                f"weather:{key}:wind_speed_10m",
                f"weather:{key}:precipitation_probability",
                f"air:{key}:us_aqi",
                f"air:{key}:pm2_5",
                f"marine:{key}:wave_height",
                f"marine:{key}:sea_surface_temperature",
            ):
                source = "openmeteo"
                add("/api/obs", {"source": source, "series": series, "limit": 1, "order": "desc"})
            add(
                "/api/obs",
                {"source": "geomag", "series": f"geomag:{key}:declination", "limit": 1, "order": "desc"},
            )
        try:
            stations = [s for s in (self.get_setting("tide_stations") or []) if isinstance(s, dict)]
        except Exception:  # noqa: BLE001
            stations = []
        if stations:
            add(
                "/api/obs",
                {"source": "tides", "series": f"tides:{stations[0].get('id')}:height", "limit": 1, "order": "desc"},
            )

        seen: set[tuple[str, str]] = set()
        ok = failed = 0
        for path, params in calls:
            key = self._cache_key(path, params)
            if key in seen:
                continue
            seen.add(key)
            try:
                self._get(path, params, use_cache=False)
                ok += 1
            except Exception:  # noqa: BLE001
                failed += 1
        logger.info("Remote prefetch: %d ok, %d failed", ok, failed)
        return {"ok": ok, "failed": failed}

    def _post(self, path: str, payload: dict[str, Any]) -> Any:
        headers = self._auth_headers()
        try:
            resp = self._client.post(path, json=payload, headers=headers, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            logger.warning("Remote POST %s -> %s", path, exc.response.status_code)
            raise

    # -- events ------------------------------------------------------------

    def query_events(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        categories: list[str] | None = None,
        min_magnitude: float | None = None,
        limit: int = 500,
        bbox: tuple[float, float, float, float] | None = None,
    ) -> list[Event]:
        params: dict[str, Any] = {"limit": limit}
        if start is not None:
            params["start"] = start.isoformat()
        if end is not None:
            params["end"] = end.isoformat()
        if categories:
            params["categories"] = ",".join(categories)
        if min_magnitude is not None:
            params["min_magnitude"] = min_magnitude
        if bbox:
            min_lat, max_lat, min_lon, max_lon = bbox
            params.update(
                {
                    "min_lat": min_lat,
                    "max_lat": max_lat,
                    "min_lon": min_lon,
                    "max_lon": max_lon,
                }
            )
        data = self._get("/api/events", params)
        return [self._event_from_dict(e) for e in data.get("events", [])]

    def get_event_by_id(self, event_id: str) -> Event | None:
        from httpx import HTTPStatusError

        try:
            data = self._get(f"/api/events/{event_id}")
        except HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        return self._event_from_dict(data)

    @staticmethod
    def _event_from_dict(data: dict[str, Any]) -> Event:
        payload = dict(data)
        if "extra" in payload and "extra_json" not in payload:
            payload["extra_json"] = payload.pop("extra") or {}
        return Event.model_validate(payload)

    # -- observations -------------------------------------------------------

    def get_series(
        self,
        source: str,
        series: str,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 10000,
        order: str = "asc",
    ) -> list[Observation]:
        data = self._get(
            "/api/obs",
            {"source": source, "series": series, "limit": limit, "order": order},
        )
        obs = [
            parsed
            for point in data.get("points", [])
            if (parsed := self._obs_from_dict(source, series, point)) is not None
        ]
        if start is not None:
            obs = [o for o in obs if o.ts >= start]
        if end is not None:
            obs = [o for o in obs if o.ts <= end]
        return obs

    def get_recent_series(self, source: str, series: str, limit: int = 120) -> list[Observation]:
        rows = self.get_series(source, series, limit=limit, order="desc")
        return list(reversed(rows))

    def get_latest_observation(self, source: str, series: str) -> Observation | None:
        rows = self.get_series(source, series, limit=1, order="desc")
        return rows[0] if rows else None

    def latest_observations(self, source: str, prefix: str, since: datetime | None = None) -> list[Observation]:
        # Call sites always pass a full series name; prefix LIKE has one match.
        data = self._get("/api/obs", {"source": source, "series": prefix, "limit": 1, "order": "desc"})
        points = data.get("points", [])
        if not points:
            return []
        obs = self._obs_from_dict(source, prefix, points[0])
        if obs is None:
            return []
        if since is not None and obs.ts < since:
            return []
        return [obs]

    @staticmethod
    def _obs_from_dict(source: str, series: str, point: dict[str, Any]) -> Observation | None:
        """Strict conversion: never fabricate a timestamp or a zero value."""
        from .models import parse_datetime

        ts = parse_datetime(point.get("ts"))
        raw_value = point.get("value")
        if ts is None or raw_value is None:
            logger.warning("Skipping malformed remote observation for %s/%s", source, series)
            return None
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            logger.warning("Skipping non-numeric remote observation for %s/%s", source, series)
            return None
        return Observation(
            source=source,
            series=series,
            ts=ts,
            value=value,
            unit=point.get("unit"),
            extra_json=dict(point.get("extra") or {}),
        )

    # -- settings -----------------------------------------------------------

    def get_setting(self, key: str, default: Any = None) -> Any:
        try:
            if key == "moon_state":
                return self._get("/api/moon/state") or default
            data = self._get("/api/settings")
            if key == "nasa_api_key":
                # Server only reports presence, never the secret: empty field
                # means "unchanged" (SettingsView skips blank keys in remote mode).
                return ""
            return data.get(key, default)
        except Exception:
            return default

    def set_setting(self, key: str, value: Any) -> None:
        if key not in WRITABLE_SETTINGS:
            raise RemoteReadOnlyError(f"setting '{key}' is not writable in remote mode")
        try:
            self._post("/api/settings", {key: value})
            self.invalidate_cache()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Remote POST /api/settings failed: %s", exc)
            raise

    # -- sources / stats -----------------------------------------------------

    def all_source_states(self) -> list[SourceState]:
        data = self._get("/api/sources")
        states = []
        for item in data.get("sources", []):
            states.append(
                SourceState(
                    source_id=item.get("source_id", "?"),
                    last_attempt=item.get("last_attempt"),
                    last_success=item.get("last_success"),
                    last_error=item.get("last_error"),
                    consecutive_failures=item.get("consecutive_failures", 0) or 0,
                    next_due=item.get("next_due"),
                    records_ingested=item.get("records_ingested", 0) or 0,
                )
            )
        return states

    def stats(self) -> dict[str, Any]:
        try:
            return dict(self._get("/api/stats"))
        except Exception:
            return {}

    # -- imagery ---------------------------------------------------------------

    def latest_asset(self, source: str) -> str | None:
        path = "/api/sun/image" if source in ("sun_imagery", "sun") else f"/api/sun/images/{source}"
        dest = self._asset_cache / f"{source}.jpg"
        # Refresh at most once per hour.
        if dest.exists() and time.time() - self._asset_ts.get(source, 0) < 3600:
            return str(dest)
        try:
            resp = self._client.get(path, timeout=self.timeout)
            if resp.status_code == 404:
                return str(dest) if dest.exists() else None
            resp.raise_for_status()
            if not resp.content.startswith(b"\xff\xd8\xff"):
                return str(dest) if dest.exists() else None
            dest.write_bytes(resp.content)
            self._asset_ts[source] = time.time()
            return str(dest)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Remote imagery %s failed: %s", source, exc)
            return str(dest) if dest.exists() else None

    def export_backup(self, dest: Path) -> Path:
        raise RemoteReadOnlyError("backup export is only available in standalone mode")

    # -- notifications (in-memory; server has no persistence endpoint yet) ------

    def add_notification(self, notif_id: str, event_id: str | None = None, category: str = "other",
                         title: str = "", severity: str = "info", fired_at: Any = None) -> None:
        if notif_id in self._notifs:
            return
        self._notifs[notif_id] = {
            "id": notif_id, "event_id": event_id, "category": category,
            "title": title, "severity": severity, "fired_at": fired_at,
        }

    def pending_notifications(self) -> list[dict[str, Any]]:
        return [n for nid, n in self._notifs.items() if nid not in self._delivered]

    def mark_notification_delivered(self, notif_id: str) -> None:
        self._delivered.add(notif_id)

    # -- unsupported local-only API ------------------------------------------------

    def __getattr__(self, name: str) -> Any:
        # (Dunders included: anything not explicitly defined is unsupported.)
        raise AttributeError(f"RemoteStore has no attribute {name!r} (not available in remote mode)")

    def close(self) -> None:
        try:
            if self._owns_client:
                self._client.close()
        except Exception:
            pass

    @property
    def data_dir(self) -> str:
        return os.environ.get("SSNOW_DATA_DIR", "") or str(self._asset_cache)
