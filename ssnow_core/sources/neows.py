"""NASA NeoWs close-approach adapter."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx

from .base import FetchResult
from ..models import Event


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_close_approach(text: str | None) -> datetime | None:
    if not text:
        return None
    for fmt in ("%Y-%b-%d %H:%M", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text.strip(), fmt)
            return parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


class NeoWsAdapter:
    def __init__(self, spec) -> None:
        self.spec = spec
        self.client_headers = {
            "User-Agent": "ss-now/0.1 (solar-system-now real-data platform)",
            "Accept": "*/*",
        }

    def _api_key(self, store) -> str:
        return store.get_setting("nasa_api_key") or "DEMO_KEY"

    def ingest(self, store, client, now=None) -> FetchResult:
        if now is None:
            now = _utcnow()

        store.begin_attempt(self.spec.id, now)
        try:
            start = now.date()
            end = (now + timedelta(days=6)).date()
            params = {
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "api_key": self._api_key(store),
            }
            response = client.get(self.spec.url, params=params, headers=self.client_headers, timeout=60.0)
            response.raise_for_status()
            store.save_snapshot(
                self.spec.id,
                str(response.url),
                response.content,
                response.headers.get("content-type", ""),
                status_code=response.status_code,
                fetched_at=now,
            )
            events, observations = self.parse(response.content, now)
        except Exception as exc:  # noqa: BLE001
            from ..redact import redact_secrets

            safe_error = redact_secrets(str(exc)) or ""
            store.record_failure(self.spec.id, now, safe_error, self.spec.cadence_seconds)
            return FetchResult(self.spec.id, None, str(self.spec.url), "", [], [], error=safe_error)

        store.upsert_events(events)
        store.upsert_observations(observations)
        store.record_success(self.spec.id, now, len(events) + len(observations), self.spec.cadence_seconds)
        from ..redact import redact_url

        return FetchResult(
            self.spec.id, response.status_code, redact_url(str(response.url)) or "",
            response.headers.get("content-type", ""), events, observations,
        )

    def parse(self, payload: bytes, now=None):
        import json

        data = json.loads(payload)
        days = data.get("near_earth_objects", {}) if isinstance(data, dict) else {}
        events: list[Event] = []
        now = now or _utcnow()
        for _date, objects in days.items():
            for obj in objects or []:
                approaches = obj.get("close_approach_data") or []
                if not approaches:
                    continue
                ca = approaches[0]
                parsed_time = _parse_close_approach(ca.get("close_approach_date_full"))
                occurred_at = parsed_time or now
                miss = ca.get("miss_distance") or {}
                vel = ca.get("relative_velocity") or {}
                diam = ((obj.get("estimated_diameter") or {}).get("kilometers") or {})
                try:
                    miss_lunar = float(miss.get("lunar")) if miss.get("lunar") is not None else None
                except (TypeError, ValueError):
                    miss_lunar = None
                try:
                    velocity = float(vel.get("kilometers_per_second")) if vel.get("kilometers_per_second") is not None else None
                except (TypeError, ValueError):
                    velocity = None
                try:
                    h_value = float(obj.get("absolute_magnitude_h")) if obj.get("absolute_magnitude_h") is not None else None
                except (TypeError, ValueError):
                    h_value = None
                extra = {
                    "time_estimated": parsed_time is None,
                    "neo_reference_id": obj.get("neo_reference_id"),
                    "absolute_magnitude_h": obj.get("absolute_magnitude_h"),
                    "miss_km": miss.get("kilometers"),
                    "miss_lunar": miss.get("lunar"),
                    "velocity_km_s": vel.get("kilometers_per_second"),
                    "hazardous": bool(obj.get("is_potentially_hazardous_asteroid")),
                    "sentry": bool(obj.get("is_sentry_object")),
                    "diameter_km_min": diam.get("estimated_diameter_min"),
                    "diameter_km_max": diam.get("estimated_diameter_max"),
                    "orbiting_body": ca.get("orbiting_body"),
                    "nasa_jpl_url": obj.get("nasa_jpl_url"),
                }
                events.append(
                    Event(
                        id=f"neows:{obj.get('id')}:{ca.get('close_approach_date', '')}",
                        source="neows",
                        upstream_id=str(obj.get("id")),
                        category="neo",
                        title=f"{obj.get('name', 'NEO')} — {miss.get('lunar', '?')} lunar distances",
                        description=f"Close approach {ca.get('close_approach_date_full', '')}",
                        occurred_at=occurred_at,
                        updated_at=None,
                        latitude=None,
                        longitude=None,
                        depth_km=None,
                        magnitude=h_value,
                        magnitude_unit="H",
                        url=obj.get("nasa_jpl_url"),
                        ingested_at=now,
                        extra_json=extra,
                    )
                )
        return events, []
