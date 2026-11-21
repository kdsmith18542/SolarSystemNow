import { useEffect, useState } from 'react';
import { api } from '../services/api';
import type { SourceState } from '../services/api';

function fmtTs(ts: string | null) {
  if (!ts) return '—';
  return new Date(ts).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function ago(ts: string | null): string {
  if (!ts) return 'never';
  const ms = Date.now() - new Date(ts).getTime();
  if (ms < 0) return 'scheduled';
  const m = Math.round(ms / 60000);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 48) return `${h}h ago`;
  return `${Math.round(h / 24)}d ago`;
}

function StatChip({ label, value, color }: { label: string; value: string | number; color: string }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/60 px-4 py-2">
      <div className="text-[10px] uppercase tracking-[0.15em] text-slate-500">{label}</div>
      <div className="text-xl font-extrabold tabular-nums" style={{ color }}>{value}</div>
    </div>
  );
}

export default function Sources() {
  const [sources, setSources] = useState<SourceState[]>([]);
  const [loading, setLoading] = useState(true);
  const [ingesting, setIngesting] = useState(false);
  const [msg, setMsg] = useState('');

  const load = () => {
    setLoading(true);
    api.sources()
      .then((r) => { setSources(r.sources); setLoading(false); })
      .catch((e) => { setMsg(String(e)); setLoading(false); });
  };

  useEffect(() => { load(); }, []);

  const ingest = () => {
    setIngesting(true);
    setMsg('');
    api.ingest()
      .then((r) => { setMsg(`Ingest complete — ${r.sources?.length ?? 0} sources run`); load(); })
      .catch((e) => setMsg(String(e)))
      .finally(() => setIngesting(false));
  };

  const enabled = sources.filter((s) => s.enabled);
  const healthy = enabled.filter((s) => s.consecutive_failures === 0);
  const failing = enabled.length - healthy.length;
  const allHealthy = failing === 0;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <StatChip label="Sources enabled" value={enabled.length} color="#e2e8f0" />
        <StatChip label="Healthy" value={healthy.length} color="#4ade80" />
        <StatChip label="Failing" value={failing} color={failing ? '#f87171' : '#64748b'} />
        <StatChip label="Disabled" value={sources.length - enabled.length} color="#64748b" />
        <StatChip label="Total records" value={sources.reduce((n, s) => n + s.records_ingested, 0)} color="#38bdf8" />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <button onClick={load} className="px-4 py-2 bg-slate-800 hover:bg-slate-700 rounded text-sm text-slate-200 border border-slate-700">Refresh</button>
        <button onClick={ingest} disabled={ingesting} className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 rounded text-sm text-white">
          {ingesting ? 'Ingesting…' : 'Ingest all due'}
        </button>
        <span className={`text-sm font-semibold ${allHealthy ? 'text-emerald-400' : failing <= 2 ? 'text-amber-400' : 'text-red-400'}`}>
          {allHealthy ? `${healthy.length}/${enabled.length} sources healthy` : `${healthy.length}/${enabled.length} healthy · ${failing} failing`}
        </span>
        {loading && <span className="text-xs text-slate-400 animate-pulse">loading…</span>}
        {msg && <span className="text-xs text-slate-400">{msg}</span>}
      </div>

      <div className="bg-slate-900/50 rounded-xl border border-slate-800 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm border-collapse">
            <thead>
              <tr className="text-slate-500 border-b border-slate-800 bg-slate-900">
                <th className="px-4 py-3">Source</th>
                <th className="px-4 py-3">Domain</th>
                <th className="px-4 py-3">Licence / attribution</th>
                <th className="px-4 py-3 text-right">Failures</th>
                <th className="px-4 py-3">Last success</th>
                <th className="px-4 py-3">Next due</th>
                <th className="px-4 py-3 text-right">Records</th>
                <th className="px-4 py-3">Last error</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {sources.map((s) => {
                const failing = s.consecutive_failures > 0;
                return (
                  <tr key={s.source_id} className={`${failing ? 'bg-amber-950/10' : ''} ${!s.enabled ? 'opacity-50' : ''} hover:bg-slate-800/40`}>
                    <td className="px-4 py-2 font-mono text-slate-200">
                      {s.source_id}
                      {!s.enabled && <span className="ml-2 text-[10px] text-slate-500">disabled</span>}
                    </td>
                    <td className="px-4 py-2 text-xs text-slate-400">{s.domain}</td>
                    <td className="px-4 py-2 text-xs text-slate-500 max-w-[18rem] truncate" title={`${s.attribution} — ${s.license}`}>
                      {s.license} · {s.attribution}
                    </td>
                    <td className="px-4 py-2 text-right text-xs tabular-nums">
                      <span style={{ color: failing ? (s.consecutive_failures > 2 ? '#f87171' : '#fbbf24') : '#4ade80' }}>
                        {s.consecutive_failures}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-xs text-slate-400" title={fmtTs(s.last_success)}>
                      {s.last_success ? ago(s.last_success) : 'never'}
                    </td>
                    <td className="px-4 py-2 text-xs text-slate-400">{fmtTs(s.next_due)}</td>
                    <td className="px-4 py-2 text-right text-xs text-slate-300 tabular-nums">{s.records_ingested}</td>
                    <td className="px-4 py-2 text-xs text-amber-300/90 max-w-[20rem] truncate" title={s.last_error ?? ''}>
                      {s.last_error ?? '—'}
                    </td>
                  </tr>
                );
              })}
              {sources.length === 0 && !loading && (
                <tr><td colSpan={8} className="px-4 py-8 text-center text-slate-500">no source state yet — run an ingest</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
