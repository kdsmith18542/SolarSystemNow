import { useEffect, useState } from 'react';
import { api } from '../services/api';
import type { MoonState } from '../services/api';
import MoonDisk from '../components/MoonDisk';

function fmtTs(ts: string | null) {
  if (!ts) return '—';
  return new Date(ts).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

export default function MoonView() {
  const [moon, setMoon] = useState<MoonState>(null);

  useEffect(() => {
    api.moon().then(setMoon);
  }, []);

  return (
    <div className="space-y-6">
      <div className="flex flex-col items-center gap-4">
        <MoonDisk illumination={moon?.illumination} phaseName={moon?.phase_name} size={200} />
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
          <div className="text-slate-300">{fmtTs(moon?.next_rise_utc)}</div>
        </div>
        <div>
          <div className="text-xs text-slate-500 uppercase">Next set (UTC)</div>
          <div className="text-slate-300">{fmtTs(moon?.next_set_utc)}</div>
        </div>
        <div>
          <div className="text-xs text-slate-500 uppercase">Computed</div>
          <div className="text-slate-300">{fmtTs(moon?.computed_at)}</div>
        </div>
      </div>
    </div>
  );
}
