import { useEffect, useState } from 'react';
import { api } from '../services/api';
import type { Event, SunSummary } from '../services/api';
import Sparkline from '../components/Sparkline';
import MoonDisk from '../components/MoonDisk';

function fmt(ts: string | null) {
  if (!ts) return '—';
  return new Date(ts).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

const CAT_COLORS: Record<string, string> = {
  earthquake: '#f87171',
  volcano: '#fb923c',
  wildfire: '#ef4444',
  storm: '#60a5fa',
  flood: '#22d3ee',
  space_weather_alert: '#e879f9',
  geomagnetic_storm: '#a78bfa',
  cme: '#f472b6',
  solar_flare: '#fbbf24',
  neo: '#a3e635',
  fireball: '#fb923c',
  severe_outlook: '#facc15',
  weather_alert: '#38bdf8',
  other: '#94a3b8',
};

const THREATS = ['QUIET', 'UNSETTLED', 'ELEVATED', 'STORM'];
const THREAT_COLORS = ['#4ade80', '#fbbf24', '#fb923c', '#f87171'];

function threatLevel(s: SunSummary | null): number {
  if (!s) return 0;
  const kp = s.kp?.value ?? 0;
  const bz = s.bz_gsm?.value ?? 0;
  const proton = s.proton_gte10?.value ?? 0;
  const dst = s.dst?.value ?? 0;
  const xr = s.xray?.class ?? '';
  if (kp >= 7 || proton >= 1000 || dst <= -100 || xr.startsWith('X')) return 3;
  if (kp >= 5 || bz <= -10 || proton >= 10 || xr.startsWith('M')) return 2;
  if (kp >= 4 || bz < 0) return 1;
  return 0;
}

function Metric({ label, value, color, sub }: { label: string; value: string; color: string; sub: string }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 flex flex-col justify-between min-w-0">
      <div className="text-[10px] uppercase tracking-[0.15em] text-slate-500 truncate">{label}</div>
      <div className="text-2xl font-extrabold tabular-nums truncate" style={{ color }}>{value}</div>
      <div className="text-[10px] text-slate-500 truncate">{sub}</div>
    </div>
  );
}

export default function Dashboard() {
  const [events, setEvents] = useState<Event[]>([]);
  const [summary, setSummary] = useState<SunSummary | null>(null);
  const [kpSeries, setKpSeries] = useState<number[]>([]);
  const [moon, setMoon] = useState<{ phase_name: string | null; illumination: number | null }>(null);
  const [tide, setTide] = useState<{ value: number; ts: string; station: string } | null>(null);
  const [neo, setNeo] = useState<any>(null);
  const [cme, setCme] = useState<any>(null);

  useEffect(() => {
    api.events({ limit: 60 }).then(({ events: evs }) => setEvents(evs)).catch(() => null);
    api.kp(90).then(r => setKpSeries(r.points.map(p => p.value))).catch(() => null);
    api.sunSummary().then(setSummary).catch(() => null);
    api.moon().then(m => setMoon({ phase_name: m.phase_name, illumination: m.illumination })).catch(() => null);
    api.neos(50).then(r => {
      const withDist = r.neos.filter(n => n.dist_lunar != null);
      withDist.sort((a, b) => (a.dist_lunar as number) - (b.dist_lunar as number));
      setNeo(withDist[0] ?? null);
    }).catch(() => null);
    api.cmeWatch().then(setCme).catch(() => null);
    api.settings.get().then(s => {
      const st = (s.tide_stations || [])[0];
      if (!st) return;
      api.obs('tides', `tides:${st.id}:height`, 1).then(r => {
        const p = r.points[r.points.length - 1];
        if (p) setTide({ value: p.value, ts: p.ts, station: st.name });
      }).catch(() => null);
    }).catch(() => null);
  }, []);

  const quake = events.find(e => e.category === 'earthquake');
  const lvl = threatLevel(summary);
  const kp = summary?.kp?.value ?? 0;
  const bz = summary?.bz_gsm?.value ?? 0;
  const proton = summary?.proton_gte10?.value ?? 0;
  const dst = summary?.dst?.value ?? 0;
  const sScale = proton >= 10000 ? 'S4' : proton >= 1000 ? 'S3' : proton >= 100 ? 'S2' : proton >= 10 ? 'S1' : '—';

  return (
    <div className="space-y-5">
      {/* Hero: composite threat + primary metrics */}
      <div className="grid grid-cols-12 gap-4">
        <div className="col-span-12 md:col-span-4 rounded-xl border border-slate-800 bg-slate-900/60 p-5 flex flex-col justify-center">
          <div className="text-[10px] uppercase tracking-[0.2em] text-slate-500 mb-1">Composite threat</div>
          <div className="text-5xl font-black" style={{ color: THREAT_COLORS[lvl] }}>{THREATS[lvl]}</div>
          <div className="text-sm text-slate-400 mt-2">
            Flare {summary?.xray?.class ?? '—'} · Kp {kp.toFixed(1)} · Bz {bz.toFixed(1)} nT
          </div>
          <div className="flex gap-1.5 mt-3">
            {THREAT_COLORS.map((c, i) => (
              <div key={i} className="h-1.5 flex-1 rounded" style={{ background: i <= lvl ? c : '#1e293b' }} />
            ))}
          </div>
        </div>
        <div className="col-span-12 md:col-span-8 grid grid-cols-2 sm:grid-cols-4 gap-3">
          <Metric label="Kp" value={summary?.kp ? kp.toFixed(1) : '—'} color={kp >= 6 ? '#f87171' : kp >= 4 ? '#fbbf24' : '#4ade80'} sub="planetary" />
          <Metric label="Bz GSM" value={summary?.bz_gsm ? `${bz.toFixed(1)} nT` : '—'} color={bz <= -10 ? '#f87171' : bz < 0 ? '#fbbf24' : '#94a3b8'} sub="southward = coupling" />
          <Metric label="Protons" value={summary?.proton_gte10 ? sScale : '—'} color={proton >= 1000 ? '#f87171' : proton >= 10 ? '#fbbf24' : '#94a3b8'} sub={summary?.proton_gte10 ? `${proton.toFixed(1)} pfu` : '≥10 MeV'} />
          <Metric label="Dst" value={summary?.dst ? `${dst.toFixed(0)} nT` : '—'} color={dst <= -100 ? '#f87171' : dst <= -50 ? '#fbbf24' : '#94a3b8'} sub="storm index" />
          <Metric label="X-ray" value={summary?.xray ? `${summary.xray.class}` : '—'} color={summary?.xray?.class.startsWith('M') || summary?.xray?.class.startsWith('X') ? '#fbbf24' : '#94a3b8'} sub="GOES 0.1–0.8 nm" />
          <Metric label="F10.7" value={summary?.f107 ? summary.f107.value.toFixed(0) : '—'} color="#fb923c" sub="sfu · SWPC" />
          <Metric label="Solar wind" value={summary?.wind_speed ? `${summary.wind_speed.value.toFixed(0)}` : '—'} color="#22d3ee" sub={summary?.wind_density ? `${summary.wind_density.value.toFixed(1)} p/cc` : 'km/s · RTSW'} />
          <Metric label="Aurora" value={summary?.aurora_max ? summary.aurora_max.value.toFixed(0) : '—'} color={(summary?.aurora_max?.value ?? 0) >= 30 ? '#4ade80' : '#94a3b8'} sub={summary?.aurora_oval ? `oval ≥ ${summary.aurora_oval.value.toFixed(0)}°` : 'OVATION max'} />
        </div>
      </div>

      {/* Trend + moon */}
      <div className="grid grid-cols-12 gap-4">
        <div className="col-span-12 md:col-span-8 rounded-xl border border-slate-800 bg-slate-900/60 p-4">
          <div className="text-[10px] uppercase tracking-[0.2em] text-slate-500 mb-2">Kp trend (recent history)</div>
          <Sparkline values={kpSeries} color="#38bdf8" max={9} />
        </div>
        <div className="col-span-12 md:col-span-4 rounded-xl border border-slate-800 bg-slate-900/60 p-4 flex items-center gap-4">
          <MoonDisk illumination={moon?.illumination ?? null} phaseName={moon?.phase_name ?? null} size={96} />
          <div className="min-w-0">
            <div className="text-[10px] uppercase tracking-[0.2em] text-slate-500">Moon</div>
            <div className="text-xl font-bold text-amber-300 truncate">{moon?.phase_name ?? '—'}</div>
            <div className="text-xs text-slate-400">{moon?.illumination != null ? `${(moon.illumination * 100).toFixed(0)}% illuminated` : '—'}</div>
          </div>
        </div>
      </div>

      {/* Event cards: quake / neo / cme / tide */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
          <div className="text-[10px] uppercase tracking-[0.2em] text-slate-500 mb-1">Latest earthquake</div>
          {quake ? (
            <>
              <div className="text-3xl font-extrabold" style={{ color: (quake.magnitude ?? 0) >= 6 ? '#f87171' : '#fbbf24' }}>
                M {quake.magnitude?.toFixed(1) ?? '—'}
              </div>
              <div className="text-xs text-slate-400 truncate">{quake.title}</div>
              <div className="text-[10px] text-slate-500">{fmt(quake.occurred_at)} · USGS</div>
            </>
          ) : <div className="text-slate-600 text-sm">no recent quakes</div>}
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
          <div className="text-[10px] uppercase tracking-[0.2em] text-slate-500 mb-1">Next close approach</div>
          {neo ? (
            <>
              <div className="text-3xl font-extrabold" style={{ color: neo.hazardous ? '#f87171' : '#a3e635' }}>
                {neo.dist_lunar?.toFixed(2)} LD
              </div>
              <div className="text-xs text-slate-400 truncate">{neo.name} · {neo.kind}</div>
              <div className="text-[10px] text-slate-500">{neo.hazardous ? 'potentially hazardous' : 'nominal'} · JPL</div>
            </>
          ) : <div className="text-slate-600 text-sm">no close approaches</div>}
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
          <div className="text-[10px] uppercase tracking-[0.2em] text-slate-500 mb-1">CME arrival (SIM)</div>
          {cme?.available && cme.result ? (
            <>
              <div className="text-3xl font-extrabold text-pink-400">
                ~{cme.result.arrival_window_low_hours.toFixed(0)}–{cme.result.arrival_window_high_hours.toFixed(0)} h
              </div>
              <div className="text-xs text-slate-400 truncate">{cme.cme_speed_km_s?.toFixed(0)} km/s · {cme.flare_class}-class</div>
              <div className="text-[10px] text-slate-500">ballistic model · not an observation</div>
            </>
          ) : <div className="text-slate-600 text-sm">no CME in window</div>}
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
          <div className="text-[10px] uppercase tracking-[0.2em] text-slate-500 mb-1">Tide level</div>
          {tide ? (
            <>
              <div className="text-3xl font-extrabold text-teal-400">{tide.value.toFixed(2)} m</div>
              <div className="text-xs text-slate-400 truncate">{tide.station}</div>
              <div className="text-[10px] text-slate-500">{fmt(tide.ts)} · NOAA CO-OPS</div>
            </>
          ) : <div className="text-slate-600 text-sm">add a station in Settings</div>}
        </div>
      </div>

      {/* Recent events */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/50 overflow-hidden">
        <div className="px-4 py-3 text-[10px] uppercase tracking-[0.2em] text-slate-500 border-b border-slate-800">Recent events</div>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm border-collapse">
            <thead>
              <tr className="text-slate-500 border-b border-slate-800 bg-slate-900">
                <th className="px-4 py-2">Time</th><th className="px-4 py-2">Category</th><th className="px-4 py-2 text-right">Mag</th><th className="px-4 py-2">Title</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {events.slice(0, 12).map(e => {
                const c = CAT_COLORS[e.category] ?? '#94a3b8';
                const seismic = ['M', 'ML', 'Mb', 'MbLg', 'Ms', 'Mw', 'md', 'MLv', ''].includes(e.magnitude_unit ?? 'M');
                return (
                  <tr key={e.id} className="hover:bg-slate-800/40">
                    <td className="px-4 py-2 text-slate-300 whitespace-nowrap">{fmt(e.occurred_at)}</td>
                    <td className="px-4 py-2">
                      <span className="text-[10px] font-bold uppercase tracking-wide px-2 py-0.5 rounded" style={{ color: c, background: `${c}1a`, border: `1px solid ${c}55` }}>{e.category}</span>
                    </td>
                    <td className="px-4 py-2 text-right text-xs tabular-nums" style={{ color: seismic && (e.magnitude ?? 0) >= 6 ? '#f87171' : '#cbd5e1' }}>
                      {e.magnitude != null ? e.magnitude.toFixed(1) : '—'}
                    </td>
                    <td className="px-4 py-2 text-slate-300 truncate max-w-md">{e.title}</td>
                  </tr>
                );
              })}
              {events.length === 0 && (
                <tr><td colSpan={4} className="px-4 py-6 text-center text-slate-500">no events — run an ingest</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="flex justify-between text-[10px] uppercase tracking-[0.15em] text-slate-600">
        <span>Data: USGS · NOAA SWPC/SPC · NASA JPL/SDO/DONKI · EONET · IEM · NOAA CO-OPS</span>
        <span>ss-now</span>
      </div>
    </div>
  );
}
