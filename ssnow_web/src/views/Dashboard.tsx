import { useEffect, useState } from 'react';
import { api } from '../services/api';
import type { Event, SunSummary } from '../services/api';
import Sparkline from '../components/Sparkline';
import { useRefreshTick } from '../hooks/useRefreshTick';
import MoonDisk from '../components/MoonDisk';

function fmt(ts: string | null) {
  if (!ts) return '—';
  return new Date(ts).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'UTC' });
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

function threatLevel(s: SunSummary | null): number | null {
  if (!s) return null;
  let level = 0;
  let known = false;
  const xr = s.xray?.class;
  if (xr) {
    known = true;
    if (xr.startsWith('X')) level = 3;
    else if (xr.startsWith('M')) level = Math.max(level, 2);
    else if (xr.startsWith('C')) level = Math.max(level, 1);
  }
  const kp = s.kp?.value;
  if (kp != null) {
    known = true;
    level = Math.max(level, kp >= 7 ? 3 : kp >= 5 ? 2 : kp >= 4 ? 1 : 0);
  }
  const bz = s.bz_gsm?.value;
  if (bz != null) {
    known = true;
    level = Math.max(level, bz <= -10 ? 2 : bz < 0 ? 1 : 0);
  }
  const proton = s.proton_gte10?.value;
  if (proton != null) {
    known = true;
    level = Math.max(level, proton >= 1000 ? 3 : proton >= 10 ? 2 : 0);
  }
  const dst = s.dst?.value;
  if (dst != null) {
    known = true;
    level = Math.max(level, dst <= -100 ? 3 : 0);
  }
  const wind = s.wind_speed?.value;
  if (wind != null) {
    known = true;
    level = Math.max(level, wind >= 600 ? 2 : wind >= 450 ? 1 : 0);
  }
  return known ? level : null;
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
  const tick = useRefreshTick();
  const [events, setEvents] = useState<Event[]>([]);
  const [summary, setSummary] = useState<SunSummary | null>(null);
  const [kpSeries, setKpSeries] = useState<number[]>([]);
  const [moon, setMoon] = useState<{ phase_name: string | null; illumination: number | null } | null>(null);
  const [neo, setNeo] = useState<any>(null);
  const [cme, setCme] = useState<any>(null);
  const [wx, setWx] = useState<any[]>([]);

  useEffect(() => {
    api.events({ limit: 60, end: new Date().toISOString() }).then(({ events: evs }) => {
      const now = Date.now();
      setEvents(evs.filter((e) => {
        const ex = (e.extra ?? {}) as any;
        return !['expires', 'expire_iso'].some((key) => ex[key] && Date.parse(ex[key]) < now);
      }));
    }).catch(() => null);
    api.kp(90).then(r => setKpSeries(r.points.map(p => p.value))).catch(() => null);
    api.sunSummary().then(setSummary).catch(() => null);
    api.moon().then(m => setMoon({ phase_name: m.phase_name, illumination: m.illumination })).catch(() => null);
    api.neos(200).then(r => {
      const now = Date.now();
      const upcoming = r.neos.filter(n =>
        n.dist_lunar != null && n.approach_at != null && n.kind !== 'sentry' &&
        new Date(n.approach_at).getTime() >= now
      );
      upcoming.sort((a, b) => new Date(a.approach_at as string).getTime() - new Date(b.approach_at as string).getTime());
      setNeo(upcoming[0] ?? null);
    }).catch(() => null);
    api.cmeWatch().then(setCme).catch(() => null);
    api.weatherNow().then(r => setWx(r.locations)).catch(() => null);
  }, [tick]);

  const quake = events.find(e => e.category === 'earthquake');
  const lvl = threatLevel(summary);
  const kp = summary?.kp?.value ?? null;
  const bz = summary?.bz_gsm?.value ?? null;
  const proton = summary?.proton_gte10?.value ?? null;
  const dst = summary?.dst?.value ?? null;
  const wind = summary?.wind_speed?.value ?? null;
  const aurora = summary?.aurora_max?.value ?? null;
  const sScale = proton == null ? '—' : proton >= 100000 ? 'S5' : proton >= 10000 ? 'S4' : proton >= 1000 ? 'S3' : proton >= 100 ? 'S2' : proton >= 10 ? 'S1' : '—';
  const threatLabel = lvl == null ? 'NO DATA' : THREATS[lvl];
  const threatColor = lvl == null ? '#64748b' : THREAT_COLORS[lvl];
  const threatMeta = [
    summary?.xray?.class ? `Flare ${summary.xray.class}` : null,
    kp != null ? `Kp ${kp.toFixed(1)}` : null,
    bz != null ? `Bz ${bz.toFixed(1)} nT` : null,
    wind != null ? `Wind ${wind.toFixed(0)} km/s` : null,
  ].filter(Boolean).join(' · ') || 'No space-weather observations yet';

  return (
    <div className="space-y-5">
      {/* Hero: composite threat + primary metrics */}
      <div className="grid grid-cols-12 gap-4">
        <div className="col-span-12 md:col-span-4 rounded-xl border border-slate-800 bg-slate-900/60 p-5 flex flex-col justify-center">
          <div className="text-[10px] uppercase tracking-[0.2em] text-slate-500 mb-1">Composite threat</div>
          <div className="text-5xl font-black" style={{ color: threatColor }}>{threatLabel}</div>
          <div className="text-sm text-slate-400 mt-2">{threatMeta}</div>
          <div className="flex gap-1.5 mt-3">
            {THREAT_COLORS.map((c, i) => (
              <div key={i} className="h-1.5 flex-1 rounded" style={{ background: lvl != null && i <= lvl ? c : '#1e293b' }} />
            ))}
          </div>
        </div>
        <div className="col-span-12 md:col-span-8 grid grid-cols-2 sm:grid-cols-4 gap-3">
          <Metric label="Kp" value={kp != null ? kp.toFixed(1) : '—'} color={kp == null ? '#64748b' : kp >= 6 ? '#f87171' : kp >= 4 ? '#fbbf24' : '#4ade80'} sub="planetary" />
          <Metric label="Bz GSM" value={bz != null ? `${bz.toFixed(1)} nT` : '—'} color={bz == null ? '#64748b' : bz <= -10 ? '#f87171' : bz < 0 ? '#fbbf24' : '#94a3b8'} sub="southward = coupling" />
          <Metric label="Protons" value={proton != null ? sScale : '—'} color={proton == null ? '#64748b' : proton >= 1000 ? '#f87171' : proton >= 10 ? '#fbbf24' : '#94a3b8'} sub={proton != null ? `${proton.toFixed(1)} pfu` : '≥10 MeV'} />
          <Metric label="Dst" value={dst != null ? `${dst.toFixed(0)} nT` : '—'} color={dst == null ? '#64748b' : dst <= -100 ? '#f87171' : dst <= -50 ? '#fbbf24' : '#94a3b8'} sub="storm index" />
          <Metric label="X-ray" value={summary?.xray?.class ?? '—'} color={!summary?.xray?.class ? '#64748b' : summary.xray.class.startsWith('M') || summary.xray.class.startsWith('X') ? '#fbbf24' : '#94a3b8'} sub="GOES 0.1–0.8 nm" />
          <Metric label="F10.7" value={summary?.f107 ? summary.f107.value.toFixed(0) : '—'} color="#fb923c" sub="sfu · SWPC" />
          <Metric label="Solar wind" value={wind != null ? `${wind.toFixed(0)}` : '—'} color={wind == null ? '#64748b' : '#22d3ee'} sub={summary?.wind_density ? `${summary.wind_density.value.toFixed(1)} p/cc` : 'km/s · RTSW'} />
          <Metric label="Aurora" value={aurora != null ? aurora.toFixed(0) : '—'} color={aurora != null && aurora >= 30 ? '#4ade80' : '#94a3b8'} sub={summary?.aurora_oval ? `oval ≥ ${summary.aurora_oval.value.toFixed(0)}°` : 'OVATION max'} />
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

      {/* Locations: weather + air + marine (desktop Local Weather card parity) */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <div className="text-[10px] uppercase tracking-[0.2em] text-slate-500 mb-3">Locations · weather · air · marine</div>
        {wx.length === 0 ? (
          <div className="text-sm text-slate-600">no locations configured — add one in Settings</div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            {wx.map((loc: any) => (
              <div key={loc.name} className="rounded-lg border border-slate-800 bg-slate-950/60 p-3">
                <div className="text-sm font-bold text-slate-100 truncate">{loc.name}</div>
                <div className="text-2xl font-extrabold text-sky-300 tabular-nums">
                  {loc.temp_c ? `${loc.temp_c.value.toFixed(1)}°C` : '—'}
                </div>
                <div className="text-[11px] text-slate-400 space-y-0.5">
                  <div>wind {loc.wind_kmh ? `${loc.wind_kmh.value.toFixed(0)} km/h` : '—'} · precip {loc.precip_pct ? `${loc.precip_pct.value.toFixed(0)}%` : '—'}</div>
                  <div>AQI {loc.aqi ? loc.aqi.value.toFixed(0) : '—'}{loc.pm25 ? ` · PM2.5 ${loc.pm25.value.toFixed(1)}` : ''}</div>
                  {loc.wave_m && <div>waves {loc.wave_m.value.toFixed(1)} m{loc.sst_c ? ` · SST ${loc.sst_c.value.toFixed(1)}°C` : ''}</div>}
                </div>
                <div className="text-[10px] text-slate-600 mt-1">{loc.temp_c ? fmt(loc.temp_c.ts) : ''} · Open-Meteo</div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Event cards: quake / neo / cme / moon */}
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
              <div className="text-[10px] text-slate-500">{neo.approach_at ? new Date(neo.approach_at).toISOString().slice(0, 10) : '—'} · {neo.hazardous ? 'potentially hazardous' : 'nominal'} · JPL</div>
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
