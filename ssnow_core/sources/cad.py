"""JPL SBDB Close-Approach Data (CAD) adapter: asteroids + comets, keyless.

Endpoint: https://ssd-api.jpl.nasa.gov/cad.api
Docs: https://ssd-api.jpl.nasa.gov/doc/cad.html
Covers both asteroids and comets (unlike NeoWs which is asteroids-only).
Keyless, so it works without a NASA API key.

Query: Earth approaches within 0.05 au (~19.4 LD) for now -> now+30d,
sorted by date, with fullname + diameter when known.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .base import HttpAdapter
from ..models import Event

AU_KM = 149597870.7
LUNAR_KM = 384400.0
CAD_URL = "https://ssd-api.jpl.nasa.gov/cad.api"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_cd(text: str | None) -> datetime | None:
    if not text:
        return None
    text = str(text).strip()
    # CAD format: "2026-Oct-15 14:38" (TDB). Also accept ISO.
    for fmt in ("%Y-%b-%d %H:%M", "%Y-%b-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _is_comet(des: str, fullname: str) -> bool:
    import re

    d = (des or "").strip()
    fn = (fullname or "").strip()
    # Comet designations contain a slash: "1P/Halley", "C/2023 A3", "P/2019 A4".
    if "/" in d:
        return True
    # Periodic comet numbers: "1P", "2P", "141P", optionally with fragment "-A".
    if re.match(r"^\d+P(-[A-Z0-9]+)?$", d):
        return True
    if re.match(r"^[CPDX]/", d):
        return True
    # Fallback: fullname with a slash that is not an asteroid provisional tag.
    # Asteroid fullnames look like "(2026 TP128)" or "99942 Apophis (2004 MN4)"
    # (no slash); comet fullnames look like "1P/Halley".
    if "/" in fn and not fn.startswith("("):
        # Exclude asteroid-style "(2004 MN4)" suffixes: they never contain "/".
        return True
    return False


def _diameter_from_h_km(h: float | None, albedo: float = 0.14) -> float | None:
    # Standard H -> diameter: D(km) = 1329 / sqrt(albedo) * 10^(-H/5)
    if h is None:
        return None
    try:
        import math

        # 1329 km formula gives diameter in km directly
        return 1329.0 / math.sqrt(albedo) * (10.0 ** (-float(h) / 5.0))
    except (TypeError, ValueError):
        return None


class CadAdapter(HttpAdapter):
    def build_request(self, now=None):
        end = now or _utcnow()
        start = end
        stop = end + timedelta(days=30)
        params = {
            "date-min": start.date().isoformat(),
            "date-max": stop.date().isoformat(),
            "dist-max": "0.05",
            "sort": "date",
            "body": "Earth",
            "fullname": "true",
            "diameter": "true",
        }
        return "GET", self.spec.url, params, {}

    def parse(self, payload: bytes, content_type: str, now=None):
        import json

        data = json.loads(payload)
        fields = data.get("fields", []) if isinstance(data, dict) else []
        rows = data.get("data", []) if isinstance(data, dict) else []
        idx = {name: i for i, name in enumerate(fields)}
        events: list[Event] = []
        now = now or _utcnow()

        def col(row, name):
            i = idx.get(name)
            if i is None or i >= len(row):
                return None
            return row[i]

        for row in rows:
            des = str(col(row, "des") or "").strip()
            fullname = str(col(row, "fullname") or col(row, "des") or "").strip()
            cd = col(row, "cd")
            occurred_at = _parse_cd(cd) or now
            try:
                dist_au = float(col(row, "dist")) if col(row, "dist") is not None else None
            except (TypeError, ValueError):
                dist_au = None
            try:
                v_rel = float(col(row, "v_rel")) if col(row, "v_rel") is not None else None
            except (TypeError, ValueError):
                v_rel = None
            try:
                h_val = float(col(row, "h")) if col(row, "h") not in (None, "") else None
            except (TypeError, ValueError):
                h_val = None
            diam = col(row, "diameter")
            try:
                diam_km = float(diam) if diam not in (None, "") else None
            except (TypeError, ValueError):
                diam_km = None
            if diam_km is None:
                diam_km = _diameter_from_h_km(h_val)
            dist_km = dist_au * AU_KM if dist_au is not None else None
            dist_lunar = dist_km / LUNAR_KM if dist_km is not None else None
            comet = _is_comet(des, fullname)
            # PHA proxy: H <= 22 and close within 0.05 au (true PHA uses MOID;
            # label honestly as candidate since CAD rows lack MOID here).
            hazardous = bool(h_val is not None and h_val <= 22.0 and dist_au is not None and dist_au <= 0.05)
            kind = "comet" if comet else "asteroid"
            ld_text = f"{dist_lunar:.1f} LD" if dist_lunar is not None else "?"
            extra = {
                "des": des,
                "fullname": fullname,
                "kind": kind,
                "is_comet": comet,
                "dist_au": dist_au,
                "dist_km": dist_km,
                "dist_lunar": dist_lunar,
                "velocity_km_s": v_rel,
                "absolute_magnitude_h": h_val,
                "diameter_km": diam_km,
                "hazardous_candidate": hazardous,
                "orbiting_body": col(row, "body") or "Earth",
                "sbdb_url": f"https://ssd.jpl.nasa.gov/tools/sbdb_lookup.html#/?sstr={des}",
                "source_feed": "jpl_cad",
            }
            events.append(
                Event(
                    id=f"cad:{des}:{cd}",
                    source="jpl_cad",
                    upstream_id=des,
                    category="neo",
                    title=f"{fullname} [{kind}] — {ld_text}",
                    description=f"Close approach {cd} · v={v_rel} km/s" if v_rel else f"Close approach {cd}",
                    occurred_at=occurred_at,
                    updated_at=None,
                    latitude=None,
                    longitude=None,
                    depth_km=None,
                    magnitude=h_val,
                    magnitude_unit="H",
                    url=extra["sbdb_url"],
                    ingested_at=now,
                    extra_json=extra,
                )
            )
        return events, []
