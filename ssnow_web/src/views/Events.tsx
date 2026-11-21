import { useEffect, useState } from 'react';
import { api } from '../services/api';
import type { Event } from '../services/api';
import { useRefreshTick } from '../hooks/useRefreshTick';

function fmt(ts: string | null) {
  if (!ts) return '—';
  return new Date(ts).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'UTC' });
}

const CATEGORIES = ['All','earthquake','volcano','wildfire','storm','flood','space_weather_alert','geomagnetic_storm','cme','solar_flare','neo','fireball','severe_outlook','weather_alert','other'];

export default function Events() {
  const tick = useRefreshTick();
  const [events, setEvents] = useState<Event[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cat, setCat] = useState('All');
  const [days, setDays] = useState(7);
  const [mag, setMag] = useState(0);
  const [selected, setSelected] = useState<Event | null>(null);
  const [sort, setSort] = useState<{ key: 'time' | 'mag'; dir: 1 | -1 }>({ key: 'time', dir: -1 });

  const sorted = [...events].sort((a, b) => {
    if (sort.key === 'mag') return ((a.magnitude ?? -1e9) - (b.magnitude ?? -1e9)) * sort.dir;
    return ((a.occurred_at ?? '') < (b.occurred_at ?? '') ? -1 : 1) * sort.dir;
  });
  const arrow = (key: 'time' | 'mag') => (sort.key === key ? (sort.dir === 1 ? ' ▲' : ' ▼') : '');

  const exportCsv = () => {
    const cols = ['id', 'source', 'category', 'title', 'occurred_at', 'latitude', 'longitude', 'magnitude', 'magnitude_unit', 'url'];
    const esc = (v: unknown) => {
      if (v == null) return '';
      const s = String(v);
      return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    };
    const lines = [cols.join(',')];
    for (const e of sorted) {
      lines.push([e.id, e.source, e.category, e.title, e.occurred_at, e.latitude, e.longitude, e.magnitude, e.magnitude_unit, e.url].map(esc).join(','));
    }
    const blob = new Blob([lines.join('\n')], { type: 'text/csv' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `ssnow-events-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const end = new Date().toISOString();
      const start = new Date(Date.now() - days * 86400000).toISOString();
      const cats = cat === 'All' ? undefined : cat;
      const r = await api.events({ start, end, categories: cats, min_magnitude: mag || undefined, limit: 500 });
      setEvents(r.events);
    } catch (e) {
      setEvents([]);
      setError(e instanceof Error ? e.message : 'Could not load events');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [cat, days, mag, tick]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2 items-end">
        <select value={cat} onChange={(e) => setCat(e.target.value)} className="bg-slate-800 border border-slate-700 rounded px-3 py-1.5 text-sm text-slate-200 focus:ring-2 focus:ring-blue-500 outline-none">
          {CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
        <input type="number" value={days} onChange={(e) => setDays(Math.max(1, Number(e.target.value) || 1))} className="w-20 bg-slate-800 border border-slate-700 rounded px-3 py-1.5 text-sm text-slate-200 focus:ring-2 focus:ring-blue-500 outline-none" />
        <input type="number" value={mag} onChange={(e) => setMag(Math.max(0, Number(e.target.value) || 0))} className="w-20 bg-slate-800 border border-slate-700 rounded px-3 py-1.5 text-sm text-slate-200 focus:ring-2 focus:ring-blue-500 outline-none" />
        <button onClick={load} className="bg-blue-600 hover:bg-blue-500 px-4 py-1.5 rounded text-sm font-medium">Apply</button>
        <button onClick={() => api.ingest().then(() => load())} className="bg-slate-700 hover:bg-slate-600 px-4 py-1.5 rounded text-sm font-medium text-slate-200">Ingest</button>
        <button onClick={exportCsv} className="bg-slate-700 hover:bg-slate-600 px-4 py-1.5 rounded text-sm font-medium text-slate-200">Export CSV</button>
        {loading && <span className="ml-2 text-xs text-slate-400 animate-pulse">loading…</span>}
        {error && <span className="ml-2 text-xs text-red-400">{error}</span>}
      </div>
      <div className="bg-slate-900/50 rounded-xl border border-slate-800 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm border-collapse">
            <thead>
              <tr className="text-slate-500 border-b border-slate-800 bg-slate-900">
                <th className="px-4 py-3 cursor-pointer hover:text-slate-300 select-none" onClick={() => setSort((s) => ({ key: 'time', dir: s.key === 'time' && s.dir === -1 ? 1 : -1 }))}>Time (UTC){arrow('time')}</th><th className="px-4 py-3">Source</th><th className="px-4 py-3">Category</th><th className="px-4 py-3 text-right cursor-pointer hover:text-slate-300 select-none" onClick={() => setSort((s) => ({ key: 'mag', dir: s.key === 'mag' && s.dir === -1 ? 1 : -1 }))}>Mag{arrow('mag')}</th><th className="px-4 py-3">Title</th><th className="px-4 py-3">Place</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {sorted.map((e) => (
                <tr
                  key={e.id}
                  className="hover:bg-slate-800/50 cursor-pointer group"
                  onClick={() => setSelected(e)}
                >
                  <td className="px-4 py-2 text-slate-300">{fmt(e.occurred_at)}</td>
                  <td className="px-4 py-2 text-xs text-slate-400">{e.source}</td>
                  <td className="px-4 py-2 text-xs text-slate-400 capitalize">{e.category}</td>
                  <td className="px-4 py-2 text-right text-xs text-slate-300">{e.magnitude != null ? e.magnitude.toFixed(1) : '—'}</td>
                  <td className="px-4 py-2 text-slate-300 truncate max-w-xs">{e.title}</td>
                  <td className="px-4 py-2 text-xs text-slate-500 truncate max-w-xs">
                    {e.latitude != null && e.longitude != null ? `${e.latitude.toFixed(2)}, ${e.longitude.toFixed(2)}` : (e.upstream_id || '—')}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="px-4 py-2 text-xs text-slate-500 border-t border-slate-800">
          {events.length} events
        </div>
      </div>
      {selected && (
        <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center">
          <div className="bg-slate-900 border border-slate-700 rounded-xl p-6 w-full max-w-2xl shadow-2xl">
            <div className="flex justify-between items-start mb-4">
              <h2 className="text-xl font-bold text-slate-100">{selected.title}</h2>
              <button onClick={() => setSelected(null)} className="text-slate-400 hover:text-white">✕</button>
            </div>
            <EventBadges ev={selected} />
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div><span className="text-slate-500 block">Source</span><span className="text-slate-300">{selected.source}</span></div>
              <div><span className="text-slate-500 block">Category</span><span className="text-slate-300">{selected.category}</span></div>
              <div><span className="text-slate-500 block">Occurred</span><span className="text-slate-300">{fmt(selected.occurred_at)}</span></div>
              <div><span className="text-slate-500 block">Magnitude</span><span className="text-slate-300">{selected.magnitude != null ? selected.magnitude.toFixed(1) + ' ' + (selected.magnitude_unit || '') : '—'}</span></div>
              <div className="col-span-2"><span className="text-slate-500 block">Description</span><span className="text-slate-300 whitespace-pre-line">{selected.description || '—'}</span></div>
              <div className="col-span-2"><span className="text-slate-500 block">URL</span>
                {selected.url && /^https?:\/\//i.test(selected.url)
                  ? <a href={selected.url} target="_blank" rel="noopener noreferrer" className="text-blue-400 underline">{selected.url}</a>
                  : <span className="text-slate-300">—</span>}
              </div>
              {Object.keys(selected.extra).length > 0 && (
                <div className="col-span-2"><span className="text-slate-500 block">Extra</span><pre className="text-xs text-slate-400 bg-slate-950 p-3 rounded overflow-auto whitespace-pre-wrap">{JSON.stringify(selected.extra, null, 2)}</pre></div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function EventBadges({ ev }: { ev: Event }) {
  const ex = (ev.extra ?? {}) as Record<string, any>;
  const badges: Array<{ text: string; color: string }> = [];
  if (ex.time_estimated) badges.push({ text: 'Estimated time — upstream timestamp missing', color: '#fbbf24' });
  if (ex.tsunami === 1 || ex.tsunami === true || ex.tsunami === '1') badges.push({ text: '🌊 TSUNAMI FLAG — check USGS/PTWC', color: '#22d3ee' });
  if (ex.alert) badges.push({ text: `PAGER alert: ${ex.alert}`, color: '#f87171' });
  if (ex.felt) badges.push({ text: `Felt reports: ${ex.felt}`, color: '#fbbf24' });
  if (ex.severity) badges.push({ text: `NWS severity: ${ex.severity} · ${ex.certainty ?? ''}/${ex.urgency ?? ''}`, color: '#fb923c' });
  if (ex.expires) badges.push({ text: `Expires: ${ex.expires}`, color: '#94a3b8' });
  if ((ex.hazardous || ex.hazardous_candidate) && !ex.is_comet) badges.push({ text: `⚠️ PHA / PHA CANDIDATE ${ex.kind ?? 'asteroid'} — ${ex.dist_lunar ?? ex.miss_lunar ?? '?'} LD`, color: '#f87171' });
  if (ex.is_comet) badges.push({ text: '☄️ Comet close approach (JPL CAD)', color: '#22d3ee' });
  if (ex.kind === 'sentry') badges.push({ text: `🎯 Sentry impact watch: PS ${ex.ps_cum} · IP ${ex.impact_probability} · ${ex.year_range ?? ''}`, color: '#f87171' });
  if (ex.kind === 'lsr') badges.push({ text: `⛈️ Storm report: ${ex.typetext} via ${ex.wfo} (${ex.source})`, color: '#60a5fa' });
  if (ex.speed || ex.type) badges.push({ text: `CME: speed ${ex.speed} km/s · type ${ex.type} · half-angle ${ex.half_angle}`, color: '#f472b6' });
  if (!badges.length) return null;
  return (
    <div className="flex flex-wrap gap-2 mb-4">
      {badges.map((b, i) => (
        <span key={i} className="text-[11px] font-semibold px-2.5 py-1 rounded-full"
          style={{ color: b.color, background: `${b.color}1a`, border: `1px solid ${b.color}55` }}>{b.text}</span>
      ))}
    </div>
  );
}
