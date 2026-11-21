import { useEffect, useState } from 'react';
import { api } from '../services/api';
import type { Event } from '../services/api';

function fmt(ts: string | null) {
  if (!ts) return '—';
  return new Date(ts).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

export default function Dashboard() {
  const [events, setEvents] = useState<Event[]>([]);
  const [kp, setKp] = useState<{ value: number; ts: string } | null>(null);
  const [moon, setMoon] = useState<{ phase_name: string | null; illumination: number | null }>(null);
  const [tide, setTide] = useState<{ value: number; ts: string; station: string } | null>(null);

  useEffect(() => {
    api.events({ limit: 50 }).then(({ events: evs }) => setEvents(evs));
    api.kp(1).then(r => {
      const p = r.points[0];
      if (p) setKp({ value: p.value, ts: p.ts });
    });
    api.moon().then(setMoon);
    api.settings.get().then(s => {
      const st = (s.tide_stations || [])[0];
      if (!st) return;
      api.obs('tides', `tides:${st.id}:height`, 1).then(r => {
        const p = r.points[r.points.length - 1];
        if (p) setTide({ value: p.value, ts: p.ts, station: st.name });
      }).catch(() => null);
    }).catch(() => null);
  }, []);

  const quake = events.find((e) => e.category === 'earthquake');
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-slate-900/50 p-6 rounded-xl border border-slate-800">
          <h2 className="text-sm text-slate-400 uppercase tracking-wider mb-2">Latest Earthquake</h2>
          {quake ? (
            <div className="space-y-1">
              <div className="text-2xl font-bold text-red-400">{quake.magnitude ?? '—'} M</div>
              <div className="text-slate-300">{quake.title}</div>
              <div className="text-xs text-slate-500">{fmt(quake.occurred_at)} · {quake.latitude?.toFixed(2)}, {quake.longitude?.toFixed(2)}</div>
            </div>
          ) : (
            <div className="text-slate-500">No data</div>
          )}
        </div>
        <div className="bg-slate-900/50 p-6 rounded-xl border border-slate-800">
          <h2 className="text-sm text-slate-400 uppercase tracking-wider mb-2">Geomagnetic (Kp)</h2>
          <div className="space-y-1">
            <div className="text-2xl font-bold text-blue-400">{kp?.value?.toFixed(1) ?? '—'}</div>
            <div className="text-slate-300">Planetary K-index · NOAA SWPC</div>
            <div className="text-xs text-slate-500">{fmt(kp?.ts ?? null)}</div>
          </div>
        </div>
        <div className="bg-slate-900/50 p-6 rounded-xl border border-slate-800">
          <h2 className="text-sm text-slate-400 uppercase tracking-wider mb-2">Moon Phase</h2>
          <div className="space-y-1">
            <div className="text-2xl font-bold text-amber-400">{moon?.phase_name ?? '—'}</div>
            <div className="text-slate-300">{moon?.illumination != null ? (moon.illumination * 100).toFixed(0) + '%' : '—'}</div>
            <div className="text-xs text-slate-500">{moon?.source ?? '—'}</div>
          </div>
        </div>
        <div className="bg-slate-900/50 p-6 rounded-xl border border-slate-800">
          <h2 className="text-sm text-slate-400 uppercase tracking-wider mb-2">Tide Level</h2>
          <div className="space-y-1">
            <div className="text-2xl font-bold text-teal-400">{tide ? tide.value.toFixed(2) + ' m' : '—'}</div>
            <div className="text-slate-300">{tide ? tide.station : 'No station configured'}</div>
            <div className="text-xs text-slate-500">{tide ? fmt(tide.ts) : 'Add a station in Settings'}</div>
          </div>
        </div>
      </div>
      <div className="bg-slate-900/50 p-6 rounded-xl border border-slate-800">
        <h2 className="text-sm text-slate-400 uppercase tracking-wider mb-4">Recent Events</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm border-collapse">
            <thead>
              <tr className="text-slate-500 border-b border-slate-800">
                <th className="pb-2">Time</th><th className="pb-2">Source</th><th className="pb-2">Category</th><th className="pb-2 text-right">Magnitude</th><th className="pb-2">Title</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {events.slice(0, 10).map((e) => (
                <tr key={e.id}>
                  <td className="text-slate-300">{fmt(e.occurred_at)}</td>
                  <td className="text-xs text-slate-400">{e.source}</td>
                  <td className="text-xs text-slate-400">{e.category}</td>
                  <td className="text-right text-xs text-slate-300">{e.magnitude != null ? e.magnitude.toFixed(1) : '—'}</td>
                  <td className="text-slate-300 truncate max-w-xs">{e.title}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
