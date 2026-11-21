import { useEffect, useState } from 'react';
import { api } from '../services/api';
import type { SimScenario } from '../services/api';

function fmt(value: any) {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'number') return Number(value).toLocaleString(undefined, { maximumFractionDigits: 4 });
  return String(value);
}

export default function SimView() {
  const [scenarios, setScenarios] = useState<SimScenario[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [params, setParams] = useState<Record<string, any>>({});
  const [result, setResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.simScenarios().then(({ scenarios: sc }) => {
      setScenarios(sc);
      if (sc.length) setSelected(sc[0].id);
    });
  }, []);

  const scenario = scenarios.find((s) => s.id === selected);

  useEffect(() => {
    if (!scenario) return;
    const defaults: Record<string, any> = {};
    for (const p of scenario.params) defaults[p.id] = p.default;
    setParams(defaults);
    setResult(null);
  }, [scenario]);

  const setParam = (id: string, value: any) => {
    setParams((prev) => ({ ...prev, [id]: value }));
  };

  const run = async () => {
    if (!scenario) return;
    setLoading(true);
    setError(null);
    try {
      const res = await api.simRun({ id: scenario.id, params });
      setResult(res.result);
    } catch (e: any) {
      setError(e.message || 'Simulation failed');
    } finally {
      setLoading(false);
    }
  };

  if (!scenario) return <div className="text-slate-400">Loading simulations…</div>;

  return (
    <div className="space-y-6">
      <div className="bg-slate-900/50 p-6 rounded-xl border border-slate-800">
        <h2 className="text-sm text-slate-400 uppercase tracking-wider mb-2">{scenario.title}</h2>
        <p className="text-slate-300 mb-3">{scenario.description}</p>
        <p className="text-xs text-slate-500 italic">Source: {scenario.citation}</p>
        <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-4">
          {scenario.params.map((p) => {
            const input = p.type === 'select' ? (
              <select
                value={String(params[p.id] ?? p.default)}
                onChange={(e) => setParam(p.id, e.target.value)}
                className="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 focus:ring-2 focus:ring-blue-500 outline-none"
              >
                {p.options?.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            ) : (
              <input
                type="number"
                value={params[p.id] ?? p.default}
                onChange={(e) => setParam(p.id, e.target.value)}
                min={p.min ?? undefined}
                max={p.max ?? undefined}
                className="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 focus:ring-2 focus:ring-blue-500 outline-none"
              />
            );
            return (
              <div key={p.id} className="flex flex-col gap-1">
                <label className="text-xs text-slate-400 flex justify-between">
                  {p.label}
                  {p.unit && <span className="opacity-50">({p.unit})</span>}
                </label>
                {input}
              </div>
            );
          })}
        </div>
        <div className="mt-4 flex gap-2">
          <button
            onClick={run}
            disabled={loading}
            className="bg-blue-600 hover:bg-blue-500 disabled:opacity-50 px-4 py-2 rounded text-sm font-medium"
          >
            {loading ? 'Running…' : 'Run simulation'}
          </button>
          {error && <span className="ml-3 text-xs text-red-400">{error}</span>}
        </div>
      </div>

      {result && (
        <div className="bg-slate-900/50 p-6 rounded-xl border border-slate-800">
          <h2 className="text-sm text-slate-400 uppercase tracking-wider mb-4">Result</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
            {Object.entries(result).map(([key, value]) => (
              <div key={key} className="bg-slate-800/50 p-3 rounded border border-slate-800/50">
                <div className="text-xs text-slate-500 uppercase mb-1">
                  {scenario.output_labels?.[key] ?? key}
                </div>
                <div className="text-slate-300 font-mono">{fmt(value)}</div>
              </div>
            ))}
          </div>
          <p className="mt-4 text-xs text-slate-500 italic">
            SIMULATION — order-of-magnitude estimate, not a forecast.
          </p>
        </div>
      )}
    </div>
  );
}
