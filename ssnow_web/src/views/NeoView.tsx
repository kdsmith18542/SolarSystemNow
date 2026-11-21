import { useEffect, useState } from 'react';
import { api } from '../services/api';
import { useRefreshTick } from '../hooks/useRefreshTick';

interface Neo {
  id: string;
  name: string;
  kind: string;
  is_comet: boolean;
  hazardous: boolean;
  hazardous_candidate: boolean;
  diameter_estimated: boolean;
  approach_at: string | null;
  dist_lunar: number | null;
  dist_km: number | null;
  velocity_km_s: number | null;
  h: number | null;
  diameter_km: number | null;
  url: string | null;
  source: string;
}

function humanSize(km: number | null): string {
  if (km == null) return '—';
  const m = km * 1000;
  if (m < 30) return `~${m.toFixed(0)} m (house)`;
  if (m < 100) return `~${m.toFixed(0)} m (airliner)`;
  if (m < 300) return `~${m.toFixed(0)} m (stadium)`;
  if (m < 1000) return `~${m.toFixed(0)} m (skyscraper+)`;
  return `~${km.toFixed(1)} km`;
}

function fmt(ts: string | null) {
  if (!ts) return '—';
  return new Date(ts).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

export default function NeoView() {
  const tick = useRefreshTick();
  const [neos, setNeos] = useState<Neo[]>([]);
  const [stats, setStats] = useState({ count: 0, pha: 0, inside_moon: 0, comets: 0 });

  useEffect(() => {
    api.neos(200).then((r) => {
      setNeos(r.neos);
      setStats({ count: r.count, pha: r.pha, inside_moon: r.inside_moon, comets: r.comets });
    }).catch(() => null);
  }, [tick]);

  const maxLD = Math.max(5, ...neos.slice(0, 12).map((n) => Math.min(n.dist_lunar ?? 5, 40)));

  return (
    <div className="space-y-4">
      <div className="bg-slate-900/50 p-4 rounded-xl border border-slate-800 text-sm text-slate-300">
        <span className="font-bold text-slate-100">{stats.count} tracked</span>
        {' · '}<span className="text-red-400">{stats.pha} PHA / PHA-candidate</span>
        {' · '}<span className="text-amber-300">{stats.inside_moon} inside Moon orbit</span>
        {' · '}<span className="text-cyan-300">{stats.comets} comets</span>
        <div className="text-xs text-slate-500 mt-1">NASA JPL CNEOS NeoWs + SBDB CAD · 1 LD = 384,400 km · schematic only, not true orbits</div>
      </div>

      <div className="bg-[#0b1020] p-4 rounded-xl border border-slate-800 overflow-x-auto">
        <div className="text-xs text-slate-400 mb-2">Lunar-distance radar (Earth left, Moon line at 1 LD)</div>
        <div className="relative h-20 min-w-[600px]">
          <div className="absolute left-10 right-4 top-1/2 h-0.5 bg-slate-700" />
          <div className="absolute top-2 bottom-6 border-l border-dashed border-slate-300" style={{ left: `${40 + (1 / maxLD) * 90}%` }}>
            <span className="text-[10px] text-slate-300 ml-1">Moon 1 LD</span>
          </div>
          <div className="absolute left-2 top-1/2 -translate-y-1/2 w-5 h-5 rounded-full bg-blue-500" title="Earth" />
          {neos.slice(0, 12).map((n, i) => {
            if (n.dist_lunar == null) return null;
            const left = 40 + (Math.min(n.dist_lunar, maxLD) / maxLD) * 90;
            return (
              <div key={n.id} className="absolute" style={{ left: `${Math.min(left, 96)}%`, top: `${20 + (i % 3) * 18}px` }} title={`${n.name} · ${n.dist_lunar?.toFixed(1)} LD`}>
                <div className={`w-2 h-2 rounded-full ${n.hazardous ? 'bg-red-500' : n.is_comet ? 'bg-cyan-400' : 'bg-lime-400'}`} />
                <div className="text-[10px] text-slate-300 whitespace-nowrap">{n.name.slice(0, 22)} · {n.dist_lunar?.toFixed(1)} LD</div>
              </div>
            );
          })}
        </div>
      </div>

      <div className="bg-slate-900/50 rounded-xl border border-slate-800 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="text-slate-500 border-b border-slate-800 bg-slate-900">
                <th className="px-4 py-3">Name</th><th className="px-4 py-3">Type</th><th className="px-4 py-3">Date (UTC)</th>
                <th className="px-4 py-3 text-right">LD</th><th className="px-4 py-3 text-right">km</th>
                <th className="px-4 py-3 text-right">Vel</th><th className="px-4 py-3">Size</th><th className="px-4 py-3">Link</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {neos.map((n) => (
                <tr key={n.id} className={n.hazardous ? 'bg-red-950/30' : 'hover:bg-slate-800/50'}>
                  <td className="px-4 py-2 text-slate-200 truncate max-w-xs">{n.name}</td>
                  <td className="px-4 py-2 text-xs capitalize text-slate-400">{n.kind}{n.kind === 'sentry' ? ' · impact watch' : n.is_comet ? '' : n.hazardous ? ' · PHA' : n.hazardous_candidate ? ' · PHA candidate' : ''}</td>
                  <td className="px-4 py-2 text-slate-300">{fmt(n.approach_at)}</td>
                  <td className="px-4 py-2 text-right text-slate-200">{n.dist_lunar != null ? n.dist_lunar.toFixed(2) : '—'}</td>
                  <td className="px-4 py-2 text-right text-slate-400">{n.dist_km != null ? Math.round(n.dist_km).toLocaleString() : '—'}</td>
                  <td className="px-4 py-2 text-right text-slate-400">{n.velocity_km_s != null ? n.velocity_km_s.toFixed(1) : '—'}</td>
                  <td className="px-4 py-2 text-xs text-slate-300">{humanSize(n.diameter_km)}{n.diameter_estimated && n.diameter_km != null ? ' (est. from H)' : ''}</td>
                  <td className="px-4 py-2">{n.url ? <a href={n.url} target="_blank" rel="noreferrer" className="text-blue-400 underline text-xs">JPL</a> : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="px-4 py-2 text-xs text-slate-500 border-t border-slate-800">{neos.length} close approaches</div>
      </div>
    </div>
  );
}
