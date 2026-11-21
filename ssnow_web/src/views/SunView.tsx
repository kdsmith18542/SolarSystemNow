import { useEffect, useState } from 'react';
import { api } from '../services/api';
import type { KpPoint, SunSummary } from '../services/api';

function fmtTs(ts: string) {
  return new Date(ts).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function Sparkline({ points }: { points: { x: number; y: number }[] }) {
  if (points.length < 2) return <div className="h-32 flex items-center justify-center text-slate-500">No data</div>;
  const w = 600, h = 160;
  const xs = points.map(p => p.x);
  const ys = points.map(p => p.y);
  const xMin = Math.min(...xs), xMax = Math.max(...xs);
  const yMin = Math.min(...ys), yMax = Math.max(...ys, 1);
  const px = (x: number) => ((x - xMin) / (xMax - xMin || 1)) * (w - 40) + 20;
  const py = (y: number) => h - 20 - ((y - yMin) / (yMax - yMin || 1)) * (h - 40);
  const d = points.map((p, i) => (i === 0 ? `M ${px(p.x)} ${py(p.y)}` : `L ${px(p.x)} ${py(p.y)}`)).join(' ');
  return (
    <svg width={w} height={h} className="text-blue-500">
      <polyline points={points.map(p => `${px(p.x)},${py(p.y)}`).join(' ')} fill="none" stroke="currentColor" strokeWidth={2} />
      <path d={`M 20 ${h-20} L ${px(points[points.length-1].x)} ${h-20} L ${px(points[points.length-1].x)} ${py(points[points.length-1].y)} Z`} fill="currentColor" fillOpacity="0.15" />
      <circle cx={px(points[points.length-1].x)} cy={py(points[points.length-1].y)} r={4} fill="currentColor" />
      <text x={px(points[points.length-1].x)} y={py(points[points.length-1].y) - 8} fontSize={11} fill="#94a3b8" textAnchor="middle">{points[points.length-1].y.toFixed(1)}</text>
    </svg>
  );
}

export default function SunView() {
  const [kp, setKp] = useState<KpPoint[]>([]);
  const [status, setStatus] = useState<string>('—');
  const [summary, setSummary] = useState<SunSummary | null>(null);

  useEffect(() => {
    api.kp(200).then(r => {
      setKp(r.points);
      const last = r.points[r.points.length - 1];
      setStatus(last ? (last.value >= 4 ? 'Elevated geomagnetic activity' : 'Quiet') : '—');
    });
    api.sunSummary().then(setSummary).catch(() => null);
  }, []);

  const latest = kp[kp.length - 1];
  const fcMax = summary?.kp_forecast?.length ? Math.max(...summary.kp_forecast.map(p => p.value)) : null;
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-slate-900/50 p-6 rounded-xl border border-slate-800">
          <h2 className="text-sm text-slate-400 uppercase tracking-wider mb-2">Planetary K-index</h2>
          <div className="text-4xl font-bold text-blue-400">{latest?.value?.toFixed(1) ?? '—'}</div>
          <div className="text-slate-300">{status}</div>
          <div className="text-xs text-slate-500">{latest ? fmtTs(latest.ts) : '—'} · NOAA SWPC</div>
          {fcMax != null && <div className="text-xs text-slate-400 mt-1">3-day forecast max Kp {fcMax.toFixed(1)}</div>}
        </div>
        <div className="bg-slate-900/50 p-6 rounded-xl border border-slate-800">
          <h2 className="text-sm text-slate-400 uppercase tracking-wider mb-2">Kp Trend (last 200 points)</h2>
          <Sparkline points={kp.map((p, i) => ({ x: i, y: p.value }))} />
        </div>
        <div className="bg-slate-900/50 p-6 rounded-xl border border-slate-800 flex flex-col">
          <h2 className="text-sm text-slate-400 uppercase tracking-wider mb-2">Solar Imagery (SDO AIA 171Å)</h2>
          <div className="h-64 bg-slate-950 rounded border border-slate-800 flex items-center justify-center overflow-hidden relative">
            <img
              src="/api/sun/image"
              alt="NASA SDO AIA 171Å"
              className="h-full w-full object-contain"
              onError={(e) => {
                e.currentTarget.style.display = 'none';
                if (e.currentTarget.parentElement) {
                  e.currentTarget.parentElement.innerText = 'No solar image cached yet';
                }
              }}
            />
          </div>
          <div className="text-xs text-slate-500 mt-2">NASA Solar Dynamics Observatory</div>
        </div>
        <div className="bg-slate-900/50 p-6 rounded-xl border border-slate-800">
          <h2 className="text-sm text-slate-400 uppercase tracking-wider mb-2">GOES X-ray (0.1–0.8 nm)</h2>
          <div className="text-4xl font-bold text-amber-400">{summary?.xray ? `${summary.xray.class}-class` : '—'}</div>
          <div className="text-slate-300 font-mono text-sm">{summary?.xray ? summary.xray.value.toExponential(2) + ' W/m²' : 'no data'}</div>
          <div className="text-xs text-slate-500">{summary?.xray ? fmtTs(summary.xray.ts) : '—'} · GOES</div>
        </div>
        <div className="bg-slate-900/50 p-6 rounded-xl border border-slate-800">
          <h2 className="text-sm text-slate-400 uppercase tracking-wider mb-2">F10.7 Solar Flux</h2>
          <div className="text-4xl font-bold text-orange-400">{summary?.f107 ? summary.f107.value.toFixed(0) : '—'}</div>
          <div className="text-slate-300">sfu</div>
          <div className="text-xs text-slate-500">{summary?.f107 ? fmtTs(summary.f107.ts) : '—'} · SWPC</div>
        </div>
        <div className="bg-slate-900/50 p-6 rounded-xl border border-slate-800">
          <h2 className="text-sm text-slate-400 uppercase tracking-wider mb-2">Aurora (OVATION)</h2>
          <div className="text-4xl font-bold text-emerald-400">{summary?.aurora_max ? summary.aurora_max.value.toFixed(0) : '—'}</div>
          <div className="text-slate-300">hemispheric max intensity{summary?.aurora_mean ? ` · band mean ${summary.aurora_mean.value.toFixed(0)}` : ''}</div>
          <div className="text-xs text-slate-500">{summary?.aurora_oval ? `oval equatorward edge ${summary.aurora_oval.value.toFixed(1)}°` : '—'} · {summary?.aurora_max ? fmtTs(summary.aurora_max.ts) : 'OVATION'}</div>
        </div>
        <WindCard />
        <div className="bg-slate-900/50 p-6 rounded-xl border border-slate-800">
          <h2 className="text-sm text-slate-400 uppercase tracking-wider mb-2">Sunspot Number</h2>
          <div className="text-4xl font-bold text-amber-300">{summary?.ssn ? summary.ssn.value.toFixed(0) : '—'}</div>
          <div className="text-slate-300">monthly{summary?.ssn_predicted ? ` · predicted ${summary.ssn_predicted.value.toFixed(0)}` : ''}</div>
          <div className="text-xs text-slate-500">{summary?.ssn ? fmtTs(summary.ssn.ts) : '—'} · SWPC solar cycle</div>
        </div>
        <ImageryWall />
        <CmeWatchCard />
        <div className="bg-slate-900/50 p-6 rounded-xl border border-slate-800">
          <h2 className="text-sm text-slate-400 uppercase tracking-wider mb-2">IMF Bz (GSM)</h2>
          <div className={`text-4xl font-bold ${summary?.bz_gsm && summary.bz_gsm.value <= -5 ? 'text-red-400' : 'text-sky-400'}`}>{summary?.bz_gsm ? summary.bz_gsm.value.toFixed(1) : '—'}</div>
          <div className="text-slate-300">nT{summary?.bt ? ` · Bt ${summary.bt.value.toFixed(1)} nT` : ''}</div>
          <div className="text-xs text-slate-500">{summary?.bz_gsm ? fmtTs(summary.bz_gsm.ts) + ` · ${summary.bz_gsm.spacecraft ?? 'RTSW'}` : '—'} · {summary?.bz_gsm && summary.bz_gsm.value <= -5 ? 'southward — storm coupling' : 'GSM'}</div>
        </div>
        <div className="bg-slate-900/50 p-6 rounded-xl border border-slate-800">
          <h2 className="text-sm text-slate-400 uppercase tracking-wider mb-2">GOES Protons ≥10 MeV</h2>
          <div className="text-4xl font-bold text-fuchsia-400">{summary?.proton_gte10 ? summary.proton_gte10.value.toFixed(1) : '—'}</div>
          <div className="text-slate-300">pfu · {summary?.proton_gte10 ? (summary.proton_gte10.value >= 10000 ? 'S4' : summary.proton_gte10.value >= 1000 ? 'S3' : summary.proton_gte10.value >= 100 ? 'S2' : summary.proton_gte10.value >= 10 ? 'S1' : 'below S1') : 'S-scale'}</div>
          <div className="text-xs text-slate-500">
            ≥50 MeV {summary?.proton_gte50 ? summary.proton_gte50.value.toFixed(2) : '—'} · ≥100 MeV {summary?.proton_gte100 ? summary.proton_gte100.value.toFixed(2) : '—'} · {summary?.proton_gte10 ? fmtTs(summary.proton_gte10.ts) : 'GOES'}
          </div>
        </div>
        <div className="bg-slate-900/50 p-6 rounded-xl border border-slate-800">
          <h2 className="text-sm text-slate-400 uppercase tracking-wider mb-2">Dst Index</h2>
          <div className="text-4xl font-bold text-violet-400">{summary?.dst ? summary.dst.value.toFixed(0) : '—'}</div>
          <div className="text-slate-300">nT · {summary?.dst ? (summary.dst.value <= -100 ? 'intense storm' : summary.dst.value <= -50 ? 'moderate storm' : 'quiet') : 'Kyoto WDC'}</div>
          <div className="text-xs text-slate-500">{summary?.dst ? fmtTs(summary.dst.ts) : '—'}</div>
        </div>
        <div className="bg-slate-900/50 p-6 rounded-xl border border-slate-800">
          <h2 className="text-sm text-slate-400 uppercase tracking-wider mb-2">Magnetic Declination</h2>
          <div className="text-4xl font-bold text-sky-300">{summary?.declination ? summary.declination.value.toFixed(1) : '—'}</div>
          <div className="text-slate-300">° {summary?.declination ? (summary.declination.value >= 0 ? 'E of true north' : 'W of true north') : 'compass correction'}</div>
          <div className="text-xs text-slate-500">{summary?.declination ? `${summary.declination.location} · ${fmtTs(summary.declination.ts)} · NOAA WMM` : 'primary location · NOAA'}</div>
        </div>
      </div>
    </div>
  );
}

function WindCard() {
  const [wind, setWind] = useState<{ value: number; ts: string } | null>(null);
  const [dens, setDens] = useState<{ value: number; ts: string } | null>(null);
  useEffect(() => {
    api.obs('swpc', 'swpc:solarwind_speed', 1).then(r => { if (r.points[0]) setWind({ value: r.points[0].value, ts: r.points[0].ts }); }).catch(() => null);
    api.obs('swpc', 'swpc:solarwind_density', 1).then(r => { if (r.points[0]) setDens({ value: r.points[0].value, ts: r.points[0].ts }); }).catch(() => null);
  }, []);
  return (
    <div className="bg-slate-900/50 p-6 rounded-xl border border-slate-800">
      <h2 className="text-sm text-slate-400 uppercase tracking-wider mb-2">Solar wind (RTSW)</h2>
      <div className="text-4xl font-bold text-cyan-400">{wind ? wind.value.toFixed(0) : '—'}</div>
      <div className="text-slate-300">km/s{dens ? ` · ${dens.value.toFixed(1)} p/cc` : ''}</div>
      <div className="text-xs text-slate-500">{wind ? fmtTs(wind.ts) : '—'} · SOLAR-1/ACE RTSW</div>
    </div>
  );
}

const CHANNEL_LABELS: Record<string, string> = {
  sun_imagery: 'SDO AIA 171Å',
  sun_sdo193: 'SDO AIA 193Å (coronal holes)',
  sun_sdo304: 'SDO AIA 304Å',
  sun_hmi: 'SDO HMI magnetogram',
  sun_lasco_c2: 'SOHO LASCO C2',
  sun_lasco_c3: 'SOHO LASCO C3',
};

function ImageryWall() {
  const [channels, setChannels] = useState<Record<string, string>>({});
  useEffect(() => {
    api.sunImages().then((r) => setChannels(r.channels)).catch(() => null);
  }, []);
  const ids = Object.keys(CHANNEL_LABELS).filter((id) => channels[id]);
  if (!ids.length) return null;
  return (
    <div className="bg-slate-900/50 p-6 rounded-xl border border-slate-800 md:col-span-3">
      <h2 className="text-sm text-slate-400 uppercase tracking-wider mb-4">Solar Imagery Wall</h2>
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
        {ids.map((id) => (
          <div key={id} className="bg-slate-950 rounded border border-slate-800 overflow-hidden">
            <img src={channels[id]} alt={CHANNEL_LABELS[id]} className="w-full aspect-square object-contain" loading="lazy"
              onError={(e) => { (e.currentTarget.parentElement as HTMLElement).style.display = 'none'; }} />
            <div className="text-[11px] text-slate-400 px-2 py-1">{CHANNEL_LABELS[id]}</div>
          </div>
        ))}
      </div>
      <div className="text-xs text-slate-500 mt-2">NASA SDO / ESA-NASA SOHO · cached hourly</div>
    </div>
  );
}

function CmeWatchCard() {
  const [watch, setWatch] = useState<{ available: boolean; cme_speed_km_s?: number; flare_class?: string; result?: { arrival_window_low_hours: number; arrival_window_high_hours: number; storm_proxy: string } } | null>(null);
  useEffect(() => {
    api.cmeWatch().then(setWatch).catch(() => null);
  }, []);
  if (!watch?.available || !watch.result) {
    return (
      <div className="bg-slate-900/50 p-6 rounded-xl border border-slate-800">
        <h2 className="text-sm text-slate-400 uppercase tracking-wider mb-2">CME Arrival (SIM)</h2>
        <div className="text-slate-300">No CME in window —</div>
        <div className="text-xs text-slate-500">Ballistic model · runs when DONKI reports a CME</div>
      </div>
    );
  }
  return (
    <div className="bg-slate-900/50 p-6 rounded-xl border border-slate-800">
      <h2 className="text-sm text-slate-400 uppercase tracking-wider mb-2">CME Arrival (SIM)</h2>
      <div className="text-2xl font-bold text-pink-400">~{watch.result.arrival_window_low_hours.toFixed(0)}–{watch.result.arrival_window_high_hours.toFixed(0)}h</div>
      <div className="text-slate-300 text-sm">{watch.cme_speed_km_s?.toFixed(0)} km/s · {watch.flare_class}-class · {watch.result.storm_proxy}</div>
      <div className="text-xs text-slate-500">Ballistic constant-speed model, NOT an observation</div>
    </div>
  );
}
