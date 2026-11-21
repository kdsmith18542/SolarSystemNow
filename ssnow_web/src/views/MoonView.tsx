import { useEffect, useState } from 'react';
import { api } from '../services/api';
import type { MoonState } from '../services/api';
import MoonDisk from '../components/MoonDisk';
import { useRefreshTick } from '../hooks/useRefreshTick';

function fmtTs(ts: string | null) {
  if (!ts) return '—';
  return new Date(ts).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'UTC' });
}

export default function MoonView() {
  const tick = useRefreshTick();
  const [moon, setMoon] = useState<MoonState | null>(null);

  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.moon().then(setMoon).catch((e) => setError(e instanceof Error ? e.message : 'Could not load Moon data'));
  }, [tick]);

  return (
    <div className="space-y-6">
      {error && <div className="text-sm text-red-400">{error}</div>}
      <div className="flex flex-col items-center gap-4">
        <MoonDisk illumination={moon?.illumination ?? null} phaseName={moon?.phase_name ?? null} size={200} />
        <div className="text-2xl font-bold text-amber-400">{moon?.phase_name ?? '—'}</div>
        {moon?.illumination != null && <div className="text-slate-300">{ (moon.illumination * 100).toFixed(0) }% illuminated</div>}
        <div className="text-xs text-slate-500">{moon?.source ?? '—'}</div>
      </div>
      <div className="bg-slate-900/50 p-6 rounded-xl border border-slate-800 grid grid-cols-2 gap-4">
        <div>
          <div className="text-xs text-slate-500 uppercase">Distance</div>
          <div className="text-slate-300">{moon?.distance_km != null ? moon.distance_km.toLocaleString() + ' km' : '—'}</div>
        </div>
        <div>
          <div className="text-xs text-slate-500 uppercase">Next rise (UTC)</div>
          <div className="text-slate-300">{fmtTs(moon?.next_rise_utc ?? null)}</div>
        </div>
        <div>
          <div className="text-xs text-slate-500 uppercase">Next set (UTC)</div>
          <div className="text-slate-300">{fmtTs(moon?.next_set_utc ?? null)}</div>
        </div>
        <div>
          <div className="text-xs text-slate-500 uppercase">Computed</div>
          <div className="text-slate-300">{fmtTs(moon?.computed_at ?? null)}</div>
        </div>
      </div>
    </div>
  );
}
