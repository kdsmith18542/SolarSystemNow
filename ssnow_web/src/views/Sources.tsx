import { useEffect, useState } from 'react';
import { api } from '../services/api';
import type { SourceState } from '../services/api';

function fmtTs(ts: string | null) {
  if (!ts) return '—';
  return new Date(ts).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

export default function Sources() {
  const [sources, setSources] = useState<SourceState[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.sources().then(r => { setSources(r.sources); setLoading(false); });
  }, []);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <button onClick={() => { setLoading(true); api.sources().then(r => { setSources(r.sources); setLoading(false); }); }} className="px-4 py-2 bg-slate-800 hover:bg-slate-700 rounded text-sm text-slate-200 border border-slate-700">Refresh</button>
        <button onClick={() => api.ingest().then(() => setLoading(true)).finally(() => setLoading(false))} className="px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded text-sm text-white">Ingest All</button>
        {loading && <span className="ml-2 text-xs text-slate-400 animate-pulse">loading…</span>}
      </div>
      <div className="bg-slate-900/50 rounded-xl border border-slate-800 overflow-hidden">
        <table className="w-full text-left text-sm border-collapse">
          <thead>
            <tr className="text-slate-500 border-b border-slate-800 bg-slate-900">
              <th className="px-4 py-3">Source</th><th className="px-4 py-3">Domain</th><th className="px-4 py-3 text-right">Failures</th><th className="px-4 py-3">Last Attempt</th><th className="px-4 py-3">Last Success</th><th className="px-4 py-3">Next Due</th><th className="px-4 py-3 text-right">Records</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {sources.map((s) => (
              <tr key={s.source_id}>
                <td className="px-4 py-2 text-slate-300 font-mono">{s.source_id}</td>
                <td className="px-4 py-2 text-xs text-slate-400">{s.domain}</td>
                <td className="px-4 py-2 text-right text-xs">{s.consecutive_failures === 0 ? <span className="text-emerald-400">0</span> : <span className="text-red-400">{s.consecutive_failures}</span>}</td>
                <td className="px-4 py-2 text-xs text-slate-400">{fmtTs(s.last_attempt)}</td>
                <td className="px-4 py-2 text-xs text-slate-400">{fmtTs(s.last_success)}</td>
                <td className="px-4 py-2 text-xs text-slate-400">{fmtTs(s.next_due)}</td>
                <td className="px-4 py-2 text-right text-xs text-slate-300">{s.records_ingested}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
