import { useEffect, useState } from 'react';
import { api } from '../services/api';
import type { Settings } from '../services/api';

export default function Settings() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [locName, setLocName] = useState('');
  const [locLat, setLocLat] = useState('');
  const [locLon, setLocLon] = useState('');
  const [tideId, setTideId] = useState('');
  const [tideName, setTideName] = useState('');
  const [nasaKey, setNasaKey] = useState('');
  const [retention, setRetention] = useState('90');
  const [msg, setMsg] = useState('');

  useEffect(() => {
    api.settings.get().then(setSettings);
  }, []);

  const addLocation = () => {
    if (!settings) return;
    const lat = parseFloat(locLat);
    const lon = parseFloat(locLon);
    if (!locName || isNaN(lat) || isNaN(lon)) { setMsg('Enter valid location'); return; }
    const locations = [...settings.locations, { name: locName, lat, lon, key: `${lat.toFixed(4)},${lon.toFixed(4)}` }];
    api.settings.set({ locations, nasa_api_key: nasaKey || undefined, retention_days: parseInt(retention) || 90 })
      .then(() => { api.settings.get().then(setSettings); setMsg('Saved'); setLocName(''); setLocLat(''); setLocLon(''); });
  };

  const addTideStation = () => {
    if (!settings || !tideId.trim()) { setMsg('Enter a station ID'); return; }
    const tide_stations = [...(settings.tide_stations || []), { id: tideId.trim(), name: tideName.trim() || tideId.trim() }];
    api.settings.set({ tide_stations })
      .then(() => { api.settings.get().then(setSettings); setMsg('Saved'); setTideId(''); setTideName(''); });
  };

  return (
    <div className="space-y-6">
      <div className="bg-slate-900/50 p-6 rounded-xl border border-slate-800">
        <h2 className="text-sm text-slate-400 uppercase tracking-wider mb-4">Location (for weather)</h2>
        <div className="flex flex-wrap gap-2">
          <input value={locName} onChange={(e) => setLocName(e.target.value)} placeholder="Name" className="bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 focus:ring-2 focus:ring-blue-500 outline-none" />
          <input value={locLat} onChange={(e) => setLocLat(e.target.value)} placeholder="Lat" className="w-24 bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 focus:ring-2 focus:ring-blue-500 outline-none" />
          <input value={locLon} onChange={(e) => setLocLon(e.target.value)} placeholder="Lon" className="w-24 bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 focus:ring-2 focus:ring-blue-500 outline-none" />
          <button onClick={addLocation} className="bg-blue-600 hover:bg-blue-500 px-4 py-2 rounded text-sm font-medium">Add</button>
          {msg && <span className="ml-2 text-xs text-emerald-400">{msg}</span>}
        </div>
        {settings && (
          <div className="mt-4">
            <h3 className="text-xs text-slate-500 uppercase mb-2">Configured locations</h3>
            <ul className="space-y-1 text-sm text-slate-300">
              {settings.locations.map(l => <li key={l.key}>{l.name} ({l.lat.toFixed(2)}, {l.lon.toFixed(2)})</li>)}
            </ul>
          </div>
        )}
      </div>
      <div className="bg-slate-900/50 p-6 rounded-xl border border-slate-800">
        <h2 className="text-sm text-slate-400 uppercase tracking-wider mb-4">Tide stations (NOAA IDs)</h2>
        <div className="flex flex-wrap gap-2">
          <input value={tideId} onChange={(e) => setTideId(e.target.value)} placeholder="Station ID (e.g. 8454000)" className="bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 focus:ring-2 focus:ring-blue-500 outline-none" />
          <input value={tideName} onChange={(e) => setTideName(e.target.value)} placeholder="Label" className="bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 focus:ring-2 focus:ring-blue-500 outline-none" />
          <button onClick={addTideStation} className="bg-blue-600 hover:bg-blue-500 px-4 py-2 rounded text-sm font-medium">Add</button>
        </div>
        {settings && (settings.tide_stations || []).length > 0 && (
          <ul className="mt-4 space-y-1 text-sm text-slate-300">
            {settings.tide_stations.map(s => <li key={s.id}>{s.name} ({s.id})</li>)}
          </ul>
        )}
        <p className="mt-2 text-xs text-slate-500">Find IDs via NOAA Tides &amp; Currents station search.</p>
      </div>
      <div className="bg-slate-900/50 p-6 rounded-xl border border-slate-800">
        <h2 className="text-sm text-slate-400 uppercase tracking-wider mb-4">NASA API key (optional)</h2>
        <input value={nasaKey} onChange={(e) => setNasaKey(e.target.value)} type="password" placeholder="DEMO_KEY used if blank" className="bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 focus:ring-2 focus:ring-blue-500 outline-none w-full max-w-xs" />
        <p className="mt-2 text-xs text-slate-500">Used for DONKI CME/flare data.</p>
      </div>
      <div className="bg-slate-900/50 p-6 rounded-xl border border-slate-800">
        <h2 className="text-sm text-slate-400 uppercase tracking-wider mb-4">Retention</h2>
        <input value={retention} onChange={(e) => setRetention(e.target.value)} type="number" placeholder="days" className="bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 focus:ring-2 focus:ring-blue-500 outline-none w-32" />
        <p className="mt-2 text-xs text-slate-500">Raw snapshot retention days.</p>
      </div>
      <div className="bg-slate-900/50 p-6 rounded-xl border border-slate-800">
        <h2 className="text-sm text-slate-400 uppercase tracking-wider mb-2">Manual ingest</h2>
        <button onClick={() => { api.ingest().then(() => setMsg('Ingest complete')); }} className="bg-blue-600 hover:bg-blue-500 px-4 py-2 rounded text-sm font-medium">Run ingestion now</button>
      </div>
    </div>
  );
}
