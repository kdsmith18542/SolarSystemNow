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

import os
import tempfile
import time
from datetime import datetime, timezone
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

    def __init__(self, base_url: str, timeout: float = 30.0, client: httpx.Client | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
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

    # -- internal ---------------------------------------------------------

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        try:
            resp = self._client.get(path, params=params, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Remote GET %s failed: %s", path, exc)
            raise

    # -- events ------------------------------------------------------------

    def query_events(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        categories: list[str] | None = None,
        min_magnitude: float | None = None,
        limit: int = 500,
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
    ) -> list[Observation]:
        data = self._get("/api/obs", {"source": source, "series": series, "limit": limit})
        obs = [self._obs_from_dict(source, series, p) for p in data.get("points", [])]
        if start is not None:
            obs = [o for o in obs if o.ts >= start]
        if end is not None:
            obs = [o for o in obs if o.ts <= end]
        return obs

    def latest_observations(self, source: str, prefix: str, since: datetime | None = None) -> list[Observation]:
        # Call sites always pass a full series name; prefix LIKE has one match.
        data = self._get("/api/obs", {"source": source, "series": prefix, "limit": 1, "order": "desc"})
        points = data.get("points", [])
        if not points:
            return []
        obs = self._obs_from_dict(source, prefix, points[0])
        if since is not None and obs.ts < since:
            return []
        return [obs]

    @staticmethod
    def _obs_from_dict(source: str, series: str, point: dict[str, Any]) -> Observation:
        from .models import parse_datetime

        ts = parse_datetime(point.get("ts")) or datetime.now(timezone.utc)
        return Observation(
            source=source,
            series=series,
            ts=ts,
            value=float(point.get("value", 0.0)),
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
            resp = self._client.post("/api/settings", json={key: value}, timeout=self.timeout)
            resp.raise_for_status()
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
