import { useEffect, useState } from 'react';
import { api } from '../services/api';

/**
 * Chrome-free broadcast overlay for OBS Browser Source.
 *
 * Open http://<host>:8123/stream (1920x1080 source, transparent-friendly).
 * Large values, no navigation, auto-refreshing; nothing interactive.
 */

interface Metric {
  label: string;
  value: string;
  color: string;
  sub?: string;
}

const C = {
  ok: '#4ade80',
  warn: '#fbbf24',
  hot: '#fb923c',
  danger: '#f87171',
  accent: '#38bdf8',
  violet: '#a78bfa',
  pink: '#f472b6',
  lime: '#a3e635',
  dim: '#94a3b8',
  faint: '#64748b',
};

function clock(): string {
  return new Date().toISOString().slice(11, 19);
}

export default function StreamOverlay() {
  const [now, setNow] = useState(clock());
  const [summary, setSummary] = useState<any>(null);
  const [kpSeries, setKpSeries] = useState<number[]>([]);
  const [quake, setQuake] = useState<any>(null);
  const [neo, setNeo] = useState<any>(null);
  const [cme, setCme] = useState<any>(null);

  useEffect(() => {
    const t = setInterval(() => setNow(clock()), 1000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    const load = () => {
      api.sunSummary().then(setSummary).catch(() => null);
      api.kp(90).then((r) => setKpSeries(r.points.map((p) => p.value))).catch(() => null);
      api.events({ categories: 'earthquake', limit: 1 }).then((r) => setQuake(r.events[0] ?? null)).catch(() => null);
      api.neos(50).then((r) => {
        const withDist = r.neos.filter((n) => n.dist_lunar != null);
        withDist.sort((a, b) => (a.dist_lunar as number) - (b.dist_lunar as number));
        setNeo(withDist[0] ?? null);
      }).catch(() => null);
      api.cmeWatch().then(setCme).catch(() => null);
    };
    load();
    const t = setInterval(load, 30_000);
    return () => clearInterval(t);
  }, []);

  const kp = summary?.kp?.value ?? 0;
  const bz = summary?.bz_gsm?.value ?? 0;
  const proton = summary?.proton_gte10?.value ?? 0;
  const dst = summary?.dst?.value ?? 0;
  const xrayClass = summary?.xray?.class ?? '—';
  const sScale = proton >= 10000 ? 'S4' : proton >= 1000 ? 'S3' : proton >= 100 ? 'S2' : proton >= 10 ? 'S1' : '—';

  const threatLevel = (kp >= 7 || proton >= 1000 || dst <= -100 || String(xrayClass).startsWith('X'))
    ? 3
    : (kp >= 5 || bz <= -10 || proton >= 10 || String(xrayClass).startsWith('M'))
      ? 2
      : (kp >= 4 || bz < 0)
        ? 1
        : 0;
  const threats = ['QUIET', 'UNSETTLED', 'ELEVATED', 'STORM'];
  const threatColors = [C.ok, C.warn, C.hot, C.danger];

  const metrics: Metric[] = [
    { label: 'Kp', value: kp.toFixed(1), color: kp >= 6 ? C.danger : kp >= 4 ? C.warn : C.ok, sub: 'planetary' },
    { label: 'Bz GSM', value: `${bz.toFixed(1)} nT`, color: bz <= -10 ? C.danger : bz < 0 ? C.warn : C.dim, sub: 'southward = coupling' },
    { label: 'Protons', value: sScale, color: proton >= 1000 ? C.danger : proton >= 10 ? C.warn : C.dim, sub: `${proton.toFixed(1)} pfu` },
    { label: 'Dst', value: `${dst.toFixed(0)} nT`, color: dst <= -100 ? C.danger : dst <= -50 ? C.warn : C.dim, sub: 'storm index' },
  ];

  // Sparkline geometry for the Kp trend.
  const spark = (() => {
    if (kpSeries.length < 2) return '';
    const w = 560, h = 64;
    const pts = kpSeries.map((v, i) => {
      const x = (i / (kpSeries.length - 1)) * w;
      const y = h - (Math.min(v, 9) / 9) * h;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    });
    return pts.join(' ');
  })();

  return (
    <div style={{ fontFamily: 'Inter, Segoe UI, system-ui, sans-serif' }} className="min-h-screen w-full bg-[#070b14] text-slate-100 p-8 select-none">
      {/* Header */}
      <div className="flex items-baseline justify-between border-b border-slate-800 pb-4">
        <div className="flex items-baseline gap-4">
          <span className="text-2xl font-extrabold tracking-[0.25em] text-sky-400">SOLAR SYSTEM NOW</span>
          <span className="text-[11px] uppercase tracking-[0.2em] text-slate-500">space · earth · weather · one feed</span>
        </div>
        <div className="text-right">
          <div className="text-3xl font-extrabold tabular-nums">{now}</div>
          <div className="text-[10px] uppercase tracking-[0.2em] text-slate-500">UTC</div>
        </div>
      </div>

      {/* Hero row */}
      <div className="grid grid-cols-12 gap-5 mt-6">
        <div className="col-span-4 rounded-2xl border border-slate-800 bg-slate-900/60 p-6 flex flex-col justify-center">
          <div className="text-[11px] uppercase tracking-[0.2em] text-slate-500 mb-1">Composite threat</div>
          <div className="text-6xl font-black" style={{ color: threatColors[threatLevel] }}>{threats[threatLevel]}</div>
          <div className="text-sm text-slate-400 mt-2">
            Flare {xrayClass}-class · Kp {kp.toFixed(1)} · Bz {bz.toFixed(1)} nT
          </div>
          <div className="flex gap-1.5 mt-4">
            {threatColors.map((c, i) => (
              <div key={i} className="h-1.5 flex-1 rounded" style={{ background: i <= threatLevel ? c : '#1e293b' }} />
            ))}
          </div>
        </div>

        <div className="col-span-8 grid grid-cols-4 gap-4">
          {metrics.map((m) => (
            <div key={m.label} className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5 flex flex-col justify-between">
              <div className="text-[11px] uppercase tracking-[0.2em] text-slate-500">{m.label}</div>
              <div className="text-4xl font-extrabold tabular-nums" style={{ color: m.color }}>{m.value}</div>
              <div className="text-[11px] text-slate-500">{m.sub}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Trend + event ticker */}
      <div className="grid grid-cols-12 gap-5 mt-5">
        <div className="col-span-8 rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
          <div className="text-[11px] uppercase tracking-[0.2em] text-slate-500 mb-2">Kp trend (recent)</div>
          {spark ? (
            <svg viewBox="0 0 560 64" className="w-full h-16" preserveAspectRatio="none">
              <polyline points={spark} fill="none" stroke={C.accent} strokeWidth={2.5} strokeLinejoin="round" strokeLinecap="round" />
            </svg>
          ) : (
            <div className="h-16 flex items-center text-slate-600 text-sm">no Kp history yet</div>
          )}
        </div>
        <div className="col-span-4 rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
          <div className="text-[11px] uppercase tracking-[0.2em] text-slate-500 mb-2">Next close approach</div>
          {neo ? (
            <>
              <div className="text-3xl font-extrabold" style={{ color: neo.hazardous ? C.danger : C.lime }}>
                {neo.dist_lunar?.toFixed(2)} LD
              </div>
              <div className="text-sm text-slate-400 truncate">{neo.name} · {neo.kind}</div>
              <div className="text-[11px] text-slate-500">{neo.hazardous ? 'POTENTIALLY HAZARDOUS' : 'nominal'}</div>
            </>
          ) : <div className="text-slate-600 text-sm">no close approaches</div>}
        </div>
      </div>

      <div className="grid grid-cols-5 gap-5 mt-5">
        <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
          <div className="text-[11px] uppercase tracking-[0.2em] text-slate-500 mb-1">Latest earthquake</div>
          {quake ? (
            <>
              <div className="text-3xl font-extrabold" style={{ color: (quake.magnitude ?? 0) >= 6 ? C.danger : C.warn }}>
                M {quake.magnitude?.toFixed(1) ?? '—'}
              </div>
              <div className="text-xs text-slate-400 truncate">{quake.title}</div>
            </>
          ) : <div className="text-slate-600 text-sm">no recent quakes</div>}
        </div>
        <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
          <div className="text-[11px] uppercase tracking-[0.2em] text-slate-500 mb-1">CME arrival (SIM)</div>
          {cme?.available && cme.result ? (
            <>
              <div className="text-3xl font-extrabold" style={{ color: C.pink }}>
                ~{cme.result.arrival_window_low_hours.toFixed(0)}–{cme.result.arrival_window_high_hours.toFixed(0)} h
              </div>
              <div className="text-xs text-slate-400">{cme.cme_speed_km_s?.toFixed(0)} km/s · {cme.flare_class}-class</div>
              <div className="text-[10px] text-slate-500">ballistic model · not an observation</div>
            </>
          ) : <div className="text-slate-600 text-sm">no CME in window</div>}
        </div>
        <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
          <div className="text-[11px] uppercase tracking-[0.2em] text-slate-500 mb-1">Solar cycle</div>
          <div className="text-3xl font-extrabold" style={{ color: C.violet }}>
            {summary?.ssn ? summary.ssn.value.toFixed(0) : '—'}
          </div>
          <div className="text-xs text-slate-400">sunspot number{summary?.ssn_predicted ? ` · predicted ${summary.ssn_predicted.value.toFixed(0)}` : ''}</div>
        </div>
        <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
          <div className="text-[11px] uppercase tracking-[0.2em] text-slate-500 mb-1">Solar wind</div>
          <div className="text-3xl font-extrabold" style={{ color: C.accent }}>
            {summary?.wind_speed ? summary.wind_speed.value.toFixed(0) : '—'}
          </div>
          <div className="text-xs text-slate-400">km/s{summary?.wind_density ? ` · ${summary.wind_density.value.toFixed(1)} p/cc` : ''}</div>
        </div>
        <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
          <div className="text-[11px] uppercase tracking-[0.2em] text-slate-500 mb-1">Aurora (OVATION)</div>
          <div className="text-3xl font-extrabold" style={{ color: (summary?.aurora_max?.value ?? 0) >= 30 ? C.ok : C.dim }}>
            {summary?.aurora_max ? summary.aurora_max.value.toFixed(0) : '—'}
          </div>
          <div className="text-xs text-slate-400">{summary?.aurora_oval ? `oval edge ≥ ${summary.aurora_oval.value.toFixed(0)}°` : 'hemispheric max'}</div>
        </div>
      </div>

      <div className="mt-6 flex justify-between text-[10px] uppercase tracking-[0.2em] text-slate-600">
        <span>Data: USGS · NOAA SWPC/SPC · NASA JPL/SDO/DONKI · EONET · IEM</span>
        <span>ss-now · /stream overlay</span>
      </div>
    </div>
  );
}
