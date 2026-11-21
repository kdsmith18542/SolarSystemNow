import { useEffect, useRef, useState } from 'react';
import { api } from '../services/api';
import type { Event } from '../services/api';
import { useRefreshTick } from '../hooks/useRefreshTick';
import 'maplibre-gl/dist/maplibre-gl.css';
import { Map, Marker, Popup } from 'maplibre-gl';
import land from '../data/ne_110m_land.json';
import borders from '../data/ne_110m_admin_0_boundary_lines_land.json';

const STYLE = 'https://demotiles.maplibre.org/style.json';

// Bundled Natural Earth outline so the map still renders without a CDN.
const OFFLINE_STYLE = {
  version: 8,
  name: 'Solar System Now offline',
  sources: {
    land: { type: 'geojson', data: land, attribution: 'Natural Earth (public domain)' },
    borders: { type: 'geojson', data: borders, attribution: 'Natural Earth (public domain)' },
  },
  layers: [
    { id: 'background', type: 'background', paint: { 'background-color': '#0b1220' } },
    { id: 'land-fill', type: 'fill', source: 'land', paint: { 'fill-color': '#1e293b' } },
    { id: 'land-outline', type: 'line', source: 'land', paint: { 'line-color': '#475569', 'line-width': 0.6 } },
    { id: 'borders', type: 'line', source: 'borders', paint: { 'line-color': '#334155', 'line-width': 0.35 } },
  ],
} as any;

const CATEGORY_COLORS: Record<string, string> = {
  earthquake: '#ef4444', // red
  volcano: '#dc2626', // dark red
  wildfire: '#f97316', // orange
  severe_storm: '#3b82f6', // blue
  storm: '#3b82f6', // IEM local storm reports ride the storm layer
  flood: '#06b6d4', // cyan
  severe_weather: '#eab308', // yellow
  weather_alert: '#22d3ee', // cyan alerts
  space_weather_alert: '#a855f6', // purple
  cme: '#ec4899', // pink
  geomagnetic_storm: '#8b5cf6', // violet
  solar_flare: '#f59e0b', // amber
  neo: '#10b981', // emerald
  fireball: '#fb923c', // orange fireball
  severe_outlook: '#eab308', // yellow SPC
  other: '#94a3b8', // slate
};

// NEXRAD base-reflectivity mosaic via Iowa State IEM WMS (free for any
// lawful purpose). US coverage only; no tiles stored — live overlay.
const RADAR_TILES = [
  'https://mesonet.agron.iastate.edu/cgi-bin/wms/nexrad/n0r.cgi?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap&LAYERS=nexrad-n0r-900913&STYLES=&FORMAT=image/png&TRANSPARENT=true&HEIGHT=256&WIDTH=256&SRS=EPSG:3857&BBOX={bbox-epsg-3857}',
];

// Simple layer groups: smooth checkboxes, not a Google-Earth clone.
// NEOs have no lat/lon (space objects) so they live in the Asteroids tab.
const LAYERS: { id: string; label: string; categories: string[] }[] = [
  { id: 'quake', label: 'Earthquakes + Tsunami', categories: ['earthquake'] },
  { id: 'volcano_fire', label: 'Volcanoes + Fires', categories: ['volcano', 'wildfire'] },
  { id: 'storm', label: 'Storms + Floods + Alerts', categories: ['storm', 'flood', 'severe_storm', 'severe_weather', 'weather_alert'] },
  { id: 'severe', label: 'SPC Outlooks', categories: ['severe_outlook'] },
  { id: 'fireball', label: 'Fireballs', categories: ['fireball'] },
  { id: 'space', label: 'Space weather', categories: ['space_weather_alert', 'cme', 'geomagnetic_storm', 'solar_flare'] },
  { id: 'other', label: 'Other', categories: ['other', 'neo'] },
];

function escapeHtml(value: unknown): string {
  return String(value ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

export default function MapView() {
  const tick = useRefreshTick();
  const [mapReady, setMapReady] = useState(false);
  const [mapError, setMapError] = useState<string | null>(null);
  const [enabled, setEnabled] = useState<Record<string, boolean>>({ quake: true, volcano_fire: true, storm: true, severe: true, fireball: true, space: true, other: false });
  const [radar, setRadar] = useState(false);
  const [auroraOval, setAuroraOval] = useState(true);
  const containerRef = useRef<HTMLDivElement>(null);
  const markersRef = useRef<Marker[]>([]);
  const mapRef = useRef<Map | null>(null);
  const eventsRef = useRef<Event[]>([]);
  const ovalRef = useRef<{ edge: number | null; north: number[][]; south: number[][] }>({ edge: null, north: [], south: [] });
  const enabledRef = useRef(enabled);
  const radarRef = useRef(radar);
  const auroraRef = useRef(auroraOval);
  enabledRef.current = enabled;
  radarRef.current = radar;
  auroraRef.current = auroraOval;

  const drawMarkers = () => {
    const map = mapRef.current;
    if (!map) return;
    markersRef.current.forEach((m) => m.remove());
    markersRef.current = [];
    // Clear previous SPC fill layers.
    try {
      if (map.getLayer('spc-fill')) map.removeLayer('spc-fill');
      if (map.getLayer('spc-line')) map.removeLayer('spc-line');
      if (map.getSource('spc')) map.removeSource('spc');
    } catch { /* ignore */ }
    // Clear previous aurora oval layer.
    try {
      if (map.getLayer('aurora-oval-line')) map.removeLayer('aurora-oval-line');
      if (map.getSource('aurora-oval')) map.removeSource('aurora-oval');
    } catch { /* ignore */ }
    // OVATION aurora oval: true equatorward-boundary polylines derived from
    // the grid when available (stored in the obs extra), otherwise a
    // constant-latitude fallback line per hemisphere.
    const oval = ovalRef.current;
    if (auroraRef.current && (oval.edge != null || oval.north.length > 1 || oval.south.length > 1) && (map as any).addSource) {
      try {
        const features: any[] = [];
        const line = (coords: number[][], title: string) => ({
          type: 'Feature' as const,
          properties: { title },
          geometry: { type: 'LineString' as const, coordinates: coords },
        });
        if (oval.north.length > 1) features.push(line(oval.north, 'OVATION auroral oval (north)'));
        if (oval.south.length > 1) features.push(line(oval.south, 'OVATION auroral oval (south)'));
        if (!features.length && oval.edge != null) {
          features.push(line([[-180, oval.edge], [180, oval.edge]], `OVATION oval edge ≈ ${oval.edge.toFixed(1)}°`));
          features.push(line([[-180, -oval.edge], [180, -oval.edge]], `OVATION oval edge ≈ ${oval.edge.toFixed(1)}°`));
        }
        (map as any).addSource('aurora-oval', { type: 'geojson', data: { type: 'FeatureCollection', features } });
        map.addLayer({
          id: 'aurora-oval-line', type: 'line', source: 'aurora-oval',
          paint: { 'line-color': '#4ade80', 'line-width': 2, 'line-dasharray': [4, 2] },
        } as any);
      } catch { /* ignore if style not ready */ }
    }
    const active = new Set<string>();
    LAYERS.filter((l) => enabledRef.current[l.id]).forEach((l) => l.categories.forEach((c) => active.add(c)));
    const isExpired = (e: Event): boolean => {
      const ex = (e.extra ?? {}) as any;
      for (const key of ['expires', 'expire_iso']) {
        if (!ex[key]) continue;
        const stamp = Date.parse(ex[key]);
        if (!Number.isNaN(stamp) && stamp < Date.now()) return true;
      }
      return false;
    };
    // SPC outlook polygons as translucent fills.
    const polys = eventsRef.current.filter(
      (e) => active.has(e.category) && !isExpired(e) && (e.extra as any)?.geometry && ['Polygon', 'MultiPolygon'].includes((e.extra as any).geometry.type)
    ).map((e) => ({ type: 'Feature' as const, properties: { title: e.title }, geometry: (e.extra as any).geometry }));
    if (polys.length && (map as any).addSource) {
      try {
        (map as any).addSource('spc', { type: 'geojson', data: { type: 'FeatureCollection', features: polys } });
        map.addLayer({ id: 'spc-fill', type: 'fill', source: 'spc', paint: { 'fill-color': '#eab308', 'fill-opacity': 0.25 } } as any);
        map.addLayer({ id: 'spc-line', type: 'line', source: 'spc', paint: { 'line-color': '#eab308', 'line-width': 1.5 } } as any);
      } catch { /* ignore if style not ready */ }
    }
    // NEXRAD radar overlay (live tiles, nothing stored).
    try {
      if (map.getLayer('radar')) map.removeLayer('radar');
      if (map.getSource('radar')) map.removeSource('radar');
      if (radarRef.current) {
        (map as any).addSource('radar', { type: 'raster', tiles: RADAR_TILES, tileSize: 256 });
        map.addLayer({ id: 'radar', type: 'raster', source: 'radar', paint: { 'raster-opacity': 0.65 } } as any);
      }
    } catch { /* ignore if style not ready */ }
    eventsRef.current.forEach((e) => {
      if (e.latitude == null || e.longitude == null) return;
      if (!active.has(e.category)) return;
      if (['weather_alert', 'severe_outlook'].includes(e.category) && isExpired(e)) return;
      const color = CATEGORY_COLORS[e.category] || CATEGORY_COLORS.other;
      const tsunami = (e.extra as any)?.tsunami === 1 || (e.extra as any)?.tsunami === true;
      const extraBadge = tsunami ? '<br/><strong style="color:#dc2626;">🌊 TSUNAMI FLAG</strong>' : '';
      const felt = (e.extra as any)?.felt;
      const feltTxt = felt ? `<br/>felt: ${escapeHtml(felt)}` : '';
      const magTxt = e.magnitude != null ? `${e.magnitude.toFixed(1)} ${escapeHtml(e.magnitude_unit || '')}` : '';
      const marker = new Marker({ color })
        .setLngLat([e.longitude, e.latitude])
        .setPopup(
          new Popup({ offset: 25 }).setHTML(
            `<div style="color:#111;"><strong>${escapeHtml(e.title || 'Event')}</strong><br/>` +
            `<em>${escapeHtml(e.category)}</em> · ${escapeHtml(e.occurred_at || '')}<br/>` +
            `${magTxt}${extraBadge}${feltTxt}<br/><em>Source: ${escapeHtml(e.source)}</em></div>`
          )
        )
        .addTo(map);
      markersRef.current.push(marker);
    });
  };

  const loadMapData = () => {
    const end = new Date().toISOString();
    const start = new Date(Date.now() - 30 * 86400000).toISOString();
    api.events({ start, end, limit: 500 }).then(({ events: evs }) => {
      eventsRef.current = evs;
      drawMarkers();
    }).catch(() => null);
    api.obs('aurora', 'aurora:oval_equatorward_deg', 1).then((r) => {
      if (r.points[0]) {
        const extra = (r.points[0].extra ?? {}) as any;
        ovalRef.current = {
          edge: r.points[0].value,
          north: Array.isArray(extra.boundary_north) ? extra.boundary_north : [],
          south: Array.isArray(extra.boundary_south) ? extra.boundary_south : [],
        };
        drawMarkers();
      }
    }).catch(() => null);
  };

  useEffect(() => {
    if (!containerRef.current) return;
    const map = new Map({
      container: containerRef.current,
      style: STYLE,
      center: [20, 10],
      zoom: 1.1,
    });
    mapRef.current = map;
    let fallback = false;
    let loadedOnce = false;
    const applyOffline = () => {
      if (fallback) return;
      fallback = true;
      setMapError(null);
      try {
        map.setStyle(OFFLINE_STYLE);
      } catch {
        setMapError('Map style/tiles unavailable (offline or blocked CDN). Event data still works below.');
      }
    };
    const onStyleReady = () => {
      loadedOnce = true;
      setMapReady(true);
      setMapError(null);
      loadMapData();
    };
    const loadTimer = window.setTimeout(() => {
      if (!loadedOnce) applyOffline();
    }, 8000);
    map.on('load', () => {
      window.clearTimeout(loadTimer);
      onStyleReady();
    });
    map.on('style.load', onStyleReady);
    map.on('error', () => {
      if (!map.isStyleLoaded()) applyOffline();
    });
    return () => {
      window.clearTimeout(loadTimer);
      markersRef.current.forEach((m) => m.remove());
      markersRef.current = [];
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    drawMarkers();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, radar, auroraOval]);

  useEffect(() => {
    if (mapReady) loadMapData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick]);

  return (
    <div className="flex-1 bg-slate-900 relative">
      <div ref={containerRef} className="absolute inset-0" />
      <div className="absolute top-3 left-3 bg-slate-950/85 backdrop-blur border border-slate-700 rounded-lg p-3 space-y-1.5 text-xs">
        <div className="text-slate-400 font-semibold uppercase tracking-wider mb-1">Layers</div>
        {LAYERS.map((l) => (
          <label key={l.id} className="flex items-center gap-2 text-slate-200 cursor-pointer hover:text-white">
            <input
              type="checkbox"
              checked={!!enabled[l.id]}
              onChange={() => setEnabled((p) => ({ ...p, [l.id]: !p[l.id] }))}
              className="accent-blue-500"
            />
            {l.label}
          </label>
        ))}
        <label className="flex items-center gap-2 text-slate-200 cursor-pointer hover:text-white border-t border-slate-700 pt-1.5 mt-1">
          <input type="checkbox" checked={radar} onChange={() => setRadar((v) => !v)} className="accent-blue-500" />
          Radar (IEM, US)
        </label>
        <label className="flex items-center gap-2 text-slate-200 cursor-pointer hover:text-white">
          <input type="checkbox" checked={auroraOval} onChange={() => setAuroraOval((v) => !v)} className="accent-blue-500" />
          Aurora oval (OVATION edge)
        </label>
        <div className="text-[10px] text-slate-500 pt-1">NEOs are space objects — see Asteroids tab.</div>
      </div>
      {!mapReady && (
        <div className="absolute inset-0 flex flex-col items-center justify-center text-slate-500 px-8 text-center">
          {mapError ?? 'Loading map…'}
        </div>
      )}
    </div>
  );
}
