"""Map view using MapLibre GL via QtWebEngine (CDN tiles/styles)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView

    HAVE_WEBENGINE = True
except Exception:  # pragma: no cover - environment dependent
    HAVE_WEBENGINE = False

from .base_view import BaseView
from .now import fmt_ts

MAP_STYLE = "https://demotiles.maplibre.org/style.json"
MAPLIBRE_CSS = "https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css"
MAPLIBRE_JS = "https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.min.js"

HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link href="%%CSS%%" rel="stylesheet">
<script src="%%JS%%" defer></script>
<style>
  body { margin: 0; padding: 0; font-family: system-ui, -apple-system, sans-serif; }
  #map { position: absolute; top: 0; bottom: 0; width: 100%; height: 100%; }
  .marker { width: 12px; height: 12px; border-radius: 50%; border: 2px solid white; cursor: pointer; box-shadow: 0 1px 3px rgba(0,0,0,0.4); }
  .legend {
    position: absolute; bottom: 20px; left: 20px;
    background: rgba(15, 23, 42, 0.85); color: #e2e8f0; padding: 8px 12px;
    border-radius: 6px; font-size: 11px; display: flex; gap: 10px;
    backdrop-filter: blur(4px); border: 1px solid rgba(255,255,255,0.1);
  }
  .legend-item { display: flex; items-center; gap: 4px; }
  .legend-dot { width: 9px; height: 9px; border-radius: 50%; display: inline-block; }
</style>
</head>
<body>
<div id="map"></div>
<div class="legend">
  <span class="legend-item"><span class="legend-dot" style="background:#ef4444"></span> Quake</span>
  <span class="legend-item"><span class="legend-dot" style="background:#dc2626"></span> Volcano</span>
  <span class="legend-item"><span class="legend-dot" style="background:#f97316"></span> Fire</span>
  <span class="legend-item"><span class="legend-dot" style="background:#3b82f6"></span> Storm/Flood</span>
  <span class="legend-item"><span class="legend-dot" style="background:#a855f7"></span> Space/Alert</span>
  <span class="legend-item"><span class="legend-dot" style="background:#fb923c"></span> Fireball</span>
  <span class="legend-item"><span class="legend-dot" style="background:#eab308"></span> SPC</span>
</div>
<script>
const geojson = %%GEOJSON%%;
const CATEGORY_COLORS = {
  earthquake: '#ef4444',
  volcano: '#dc2626',
  wildfire: '#f97316',
  severe_storm: '#3b82f6',
  flood: '#06b6d4',
  severe_weather: '#eab308',
  space_weather_alert: '#a855f7',
  cme: '#ec4899',
  geomagnetic_storm: '#8b5cf6',
  neo: '#10b981',
  fireball: '#fb923c',
  severe_outlook: '#eab308',
  other: '#94a3b8'
};

function initMap() {
  if (typeof maplibregl === 'undefined') {
    document.body.innerHTML = '<div style="padding:20px;color:#666;">Map requires internet access (MapLibre CDN). Open the Events tab for offline data.</div>';
    return;
  }
  const map = new maplibregl.Map({
    container: 'map',
    style: '%%STYLE%%',
    center: [%%LON%%, %%LAT%%],
    zoom: %%ZOOM%%,
  });
  map.on('load', () => {
    // NEXRAD radar overlay (IEM WMS, US coverage, live tiles — nothing stored).
    if ('%%RADAR%%' === 'true') {
      map.addSource('radar', { type: 'raster', tiles: ['https://mesonet.agron.iastate.edu/cgi-bin/wms/nexrad/n0r.cgi?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap&LAYERS=nexrad-n0r-900913&STYLES=&FORMAT=image/png&TRANSPARENT=true&HEIGHT=256&WIDTH=256&SRS=EPSG:3857&BBOX={bbox-epsg-3857}'], tileSize: 256 });
      map.addLayer({ id: 'radar', type: 'raster', source: 'radar', paint: { 'raster-opacity': 0.65 } });
    }
    // SPC outlook polygons as translucent fills (forecast areas, not events).
    const polys = { type: 'FeatureCollection', features: geojson.features.filter(f => f.geometry && (f.geometry.type === 'Polygon' || f.geometry.type === 'MultiPolygon')) };
    if (polys.features.length) {
      map.addSource('spc', { type: 'geojson', data: polys });
      map.addLayer({ id: 'spc-fill', type: 'fill', source: 'spc', paint: { 'fill-color': '#eab308', 'fill-opacity': 0.25 } });
      map.addLayer({ id: 'spc-line', type: 'line', source: 'spc', paint: { 'line-color': '#eab308', 'line-width': 1.5 } });
    }
    for (const feature of geojson.features) {
      if (!feature.geometry || feature.geometry.type !== 'Point') continue;
      const [lon, lat] = feature.geometry.coordinates;
      const el = document.createElement('div');
      el.className = 'marker';
      const props = feature.properties;
      el.style.backgroundColor = CATEGORY_COLORS[props.category] || CATEGORY_COLORS.other;
      const popup = new maplibregl.Popup({ offset: 8 }).setHTML(
        `<div style="color:#111;"><strong>${props.title || 'Event'}</strong><br>${props.category} · ${props.time || ''}<br>${props.magnitude ? props.magnitude + ' ' + (props.magnitude_unit || '') : ''}</div>`
      );
      new maplibregl.Marker(el).setLngLat([lon, lat]).setPopup(popup).addTo(map);
    }
  });
}
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initMap);
} else {
  initMap();
}
</script>
</body>
</html>"""


class MapView(BaseView):
    # Simple layer groups — smooth checkboxes, not a Google-Earth clone.
    # NEOs have no lat/lon (space objects) and live in the Asteroids tab.
    LAYERS: list[tuple[str, str, list[str]]] = [
        ("quake", "Quakes+Tsunami", ["earthquake"]),
        ("volcano_fire", "Volcano+Fire", ["volcano", "wildfire"]),
        ("storm", "Storm/Flood/Alerts", ["storm", "flood", "weather_alert"]),
        ("severe", "SPC Outlooks", ["severe_outlook"]),
        ("fireball", "Fireballs", ["fireball"]),
        ("space", "Space weather", ["space_weather_alert", "cme", "geomagnetic_storm", "solar_flare"]),
        ("other", "Other", ["other"]),
    ]

    def __init__(self, store) -> None:
        super().__init__(store)
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(4, 2, 4, 2)
        self._boxes: dict[str, QCheckBox] = {}
        for lid, label, _cats in self.LAYERS:
            box = QCheckBox(label)
            box.setChecked(lid != "other")
            box.stateChanged.connect(lambda _s, _lid=lid: self.refresh())
            self._boxes[lid] = box
            toolbar.addWidget(box)
        self._radar_box = QCheckBox("Radar (IEM, US)")
        self._radar_box.setChecked(False)
        self._radar_box.setToolTip("Live NEXRAD mosaic overlay (US coverage, nothing stored)")
        self._radar_box.stateChanged.connect(lambda _s: self.refresh())
        toolbar.addWidget(self._radar_box)
        self._reset_btn = QPushButton("Reset view")
        self._reset_btn.setToolTip("Back to the full-world view")
        self._reset_btn.clicked.connect(self.reset_view)
        toolbar.addWidget(self._reset_btn)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)
        self._center: tuple[float, float] | None = None  # (lon, lat) focus from Show-on-Map
        self._zoom: float | None = None
        if not HAVE_WEBENGINE:
            self.label = QLabel("QtWebEngine is not available in this build.")
            layout.addWidget(self.label)
            self.view = None
            return
        self.view = QWebEngineView()
        self.view.setHtml("<p>Loading map…</p>")
        layout.addWidget(self.view)
        self.refresh()

    def refresh(self) -> None:
        if self.view is None:
            return
        active: set[str] = set()
        for lid, _label, cats in self.LAYERS:
            box = self._boxes.get(lid)
            if box is None or box.isChecked():
                active.update(cats)
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=30)
        events = self.store.query_events(start=start, end=end, limit=500)
        features = []
        for event in events:
            if event.latitude is None or event.longitude is None:
                continue
            if event.category not in active:
                continue
            ex = event.extra_json or {}
            badge = " 🌊 TSUNAMI" if ex.get("tsunami") in (1, True) else ""
            felt = ex.get("felt")
            detail = f"{event.magnitude:.1f}" if event.magnitude is not None else ""
            if felt:
                detail += f" felt:{felt}"
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "title": event.title + badge,
                        "category": event.category,
                        "time": fmt_ts(event.occurred_at),
                        "magnitude": detail,
                        "magnitude_unit": event.magnitude_unit or "",
                        "source": event.source,
                    },
                    "geometry": {
                        "type": "Point",
                        "coordinates": [event.longitude, event.latitude],
                    },
                }
            )
            # SPC outlook polygon overlay (forecast area fill).
            geom = (event.extra_json or {}).get("geometry")
            if event.category == "severe_outlook" and isinstance(geom, dict) and geom.get("type") in ("Polygon", "MultiPolygon"):
                features.append(
                    {
                        "type": "Feature",
                        "properties": {
                            "title": event.title,
                            "category": event.category,
                            "time": fmt_ts(event.occurred_at),
                            "magnitude": detail,
                            "magnitude_unit": event.magnitude_unit or "",
                            "source": event.source,
                        },
                        "geometry": geom,
                    }
                )
        geojson = json.dumps({"type": "FeatureCollection", "features": features})
        lon, lat = self._center if self._center is not None else (20.0, 10.0)
        zoom = self._zoom if self._zoom is not None else 1.1
        html = (
            HTML_TEMPLATE.replace("%%CSS%%", MAPLIBRE_CSS)
            .replace("%%JS%%", MAPLIBRE_JS)
            .replace("%%STYLE%%", MAP_STYLE)
            .replace("%%RADAR%%", "true" if (self._radar_box is not None and self._radar_box.isChecked()) else "false")
            .replace("%%LON%%", f"{lon:.4f}")
            .replace("%%LAT%%", f"{lat:.4f}")
            .replace("%%ZOOM%%", f"{zoom:.1f}")
            .replace("%%GEOJSON%%", geojson)
        )
        self.view.setHtml(html, QUrl("about:blank"))

    def focus(self, latitude: float, longitude: float) -> None:
        """Center the map on an event (Show on Map); sticky until Reset."""
        self._center = (longitude, latitude)
        self._zoom = 5.0
        self.refresh()

    def reset_view(self) -> None:
        self._center = None
        self._zoom = None
        self.refresh()
