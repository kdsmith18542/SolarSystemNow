"""GeoJSON helpers shared by event adapters."""

from __future__ import annotations

from typing import Any


def _ring_centroid(ring: Any) -> tuple[float | None, float | None]:
    try:
        pairs = [(float(point[1]), float(point[0])) for point in ring if len(point) > 1]
    except (TypeError, ValueError, IndexError):
        return None, None
    if not pairs:
        return None, None
    return sum(lat for lat, _ in pairs) / len(pairs), sum(lon for _, lon in pairs) / len(pairs)


def geometry_centroid(geometry: dict[str, Any] | None) -> tuple[float | None, float | None]:
    """Return (lat, lon) for Point/Polygon/MultiPolygon, else (None, None)."""
    if not isinstance(geometry, dict):
        return None, None
    kind = geometry.get("type")
    coords = geometry.get("coordinates")
    if kind == "Point":
        try:
            return float(coords[1]), float(coords[0])
        except (TypeError, ValueError, IndexError):
            return None, None
    if kind == "Polygon" and coords:
        return _ring_centroid(coords[0])
    if kind == "MultiPolygon" and coords:
        # Use the first polygon ring; alerts are usually a handful of cells.
        first = coords[0]
        if first:
            return _ring_centroid(first[0])
    return None, None


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two WGS84 points."""
    import math

    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 6371.0088 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
