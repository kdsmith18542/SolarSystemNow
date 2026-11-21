import { useEffect, useState } from 'react';
import { api } from '../services/api';
import type { Event } from '../services/api';

function fmt(ts: string | null) {
  if (!ts) return '—';
  return new Date(ts).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

const CATEGORIES = ['All','earthquake','volcano','wildfire','storm','flood','space_weather_alert','geomagnetic_storm','cme','solar_flare','neo','fireball','severe_outlook','weather_alert','other'];

export default function Events() {
  const [events, setEvents] = useState<Event[]>([]);
  const [loading, setLoading] = useState(false);
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

  const load = async () => {
    setLoading(true);
    try {
      const end = new Date().toISOString();
      const start = new Date(Date.now() - days * 86400000).toISOString();
      const cats = cat === 'All' ? undefined : cat;
      const r = await api.events({ start, end, categories: cats, min_magnitude: mag || undefined, limit: 500 });
      setEvents(r.events);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [cat, days, mag]);

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
        {loading && <span className="ml-2 text-xs text-slate-400 animate-pulse">loading…</span>}
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
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div><span className="text-slate-500 block">Source</span><span className="text-slate-300">{selected.source}</span></div>
              <div><span className="text-slate-500 block">Category</span><span className="text-slate-300">{selected.category}</span></div>
              <div><span className="text-slate-500 block">Occurred</span><span className="text-slate-300">{fmt(selected.occurred_at)}</span></div>
              <div><span className="text-slate-500 block">Magnitude</span><span className="text-slate-300">{selected.magnitude != null ? selected.magnitude.toFixed(1) + ' ' + (selected.magnitude_unit || '') : '—'}</span></div>
              <div colSpan={2}><span className="text-slate-500 block">Description</span><span className="text-slate-300 whitespace-pre-line">{selected.description || '—'}</span></div>
              <div colSpan={2}><span className="text-slate-500 block">URL</span><a href={selected.url || '#'} target="_blank" rel="noopener noreferrer" className="text-blue-400 underline">{selected.url || '—'}</a></div>
              {Object.keys(selected.extra).length > 0 && (
                <div colSpan={2}><span className="text-slate-500 block">Extra</span><pre className="text-xs text-slate-400 bg-slate-950 p-3 rounded overflow-auto whitespace-pre-wrap">{JSON.stringify(selected.extra, null, 2)}</pre></div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
