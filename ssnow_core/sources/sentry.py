"""JPL CNEOS Sentry impact-risk adapter (summary mode).

Endpoint: https://ssd-api.jpl.nasa.gov/sentry.api (no params = summary table S)
Response: {"signature", "count", "data": [{des, fullname, ps_cum, ps_max,
ip, diameter, h, v_inf, n_imp, range, last_obs, ts_max, id}, ...]}

2255 objects as of 2026-11; we keep the top 40 by cumulative Palermo scale
so the store carries the watch-list streamers actually read, not the tail.

Events use category "neo" with kind="sentry" (no close-approach distance —
they sort to the bottom of the LD radar, honestly labelled). Magnitude =
cumulative Palermo scale, unit "PS".

NASA public data, keyless. Fair use: single request per cycle (cadence 24h).
"""

from __future__ import annotations

from datetime import datetime, timezone

from .base import HttpAdapter
from ..models import Event


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _fnum(value) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


KEEP_TOP_N = 40


class SentryAdapter(HttpAdapter):
    def build_request(self, now=None):
        return "GET", self.spec.url, None, {}

    def parse(self, payload: bytes, content_type: str, now=None):
        import json

        data = json.loads(payload)
        rows = data.get("data", []) if isinstance(data, dict) else []
        now = now or _utcnow()
        scored: list[tuple[float, dict]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            ps = _fnum(row.get("ps_cum"))
            if ps is None:
                continue
            scored.append((ps, row))
        # Highest (least-negative) Palermo scale first.
        scored.sort(key=lambda p: p[0], reverse=True)
        events: list[Event] = []
        for ps_cum, row in scored[:KEEP_TOP_N]:
            des = str(row.get("des") or "").strip()
            fullname = str(row.get("fullname") or des).strip()
            ps_max = _fnum(row.get("ps_max"))
            h_val = _fnum(row.get("h"))
            try:
                last_obs = datetime.strptime(str(row.get("last_obs") or ""), "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                last_obs = now
            extra = {
                "des": des,
                "fullname": fullname,
                "kind": "sentry",
                "is_sentry": True,
                "ps_cum": ps_cum,
                "ps_max": ps_max,
                "impact_probability": _fnum(row.get("ip")),
                "diameter_km": _fnum(row.get("diameter")),
                "absolute_magnitude_h": h_val,
                "v_inf_km_s": _fnum(row.get("v_inf")),
                "n_impactors": row.get("n_imp"),
                "year_range": row.get("range"),
                "torino_max": row.get("ts_max"),
                "sbdb_url": f"https://ssd.jpl.nasa.gov/tools/sbdb_lookup.html#/?sstr={des}",
            }
            events.append(
                Event(
                    id=f"sentry:{row.get('id') or des}",
                    source="sentry",
                    upstream_id=des,
                    category="neo",
                    title=f"Sentry {fullname} — PS {ps_cum:.2f}",
                    description=f"CNEOS Sentry impact monitoring: {row.get('n_imp')} virtual impactor(s), {row.get('range')}",
                    occurred_at=last_obs,
                    updated_at=None,
                    latitude=None,
                    longitude=None,
                    depth_km=None,
                    magnitude=ps_cum,
                    magnitude_unit="PS",
                    url=extra["sbdb_url"],
                    ingested_at=now,
                    extra_json=extra,
                )
            )
        return events, []
