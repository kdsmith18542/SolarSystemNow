import { useEffect, useState } from 'react';
import { api, getWriteToken, setWriteToken } from '../services/api';
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
  const [token, setToken] = useState(getWriteToken());
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);

  const load = () => api.settings.get().then(setSettings).catch((e) => setMsg(String(e)));

  useEffect(() => { load(); }, []);

  const save = (body: Parameters<typeof api.settings.set>[0], okMsg: string) => {
    setBusy(true);
    setMsg('');
    api.settings.set(body)
      .then(() => load().then(() => setMsg(okMsg)))
      .catch((e) => setMsg(String(e)))
      .finally(() => setBusy(false));
  };

  const addLocation = () => {
    if (!settings) return;
    const lat = parseFloat(locLat);
    const lon = parseFloat(locLon);
    if (!locName.trim() || isNaN(lat) || isNaN(lon)) { setMsg('Enter a name, latitude and longitude'); return; }
    const key = `${lat.toFixed(4)},${lon.toFixed(4)}`;
    if (settings.locations.some((l) => l.key === key)) { setMsg('That location is already configured'); return; }
    const locations = [...settings.locations, { name: locName.trim(), lat, lon, key }];
    save({ locations }, 'Location saved');
    setLocName(''); setLocLat(''); setLocLon('');
  };

  const removeLocation = (key: string) => {
    if (!settings) return;
    save({ locations: settings.locations.filter((l) => l.key !== key) }, 'Location removed');
  };

  const addTideStation = () => {
    if (!settings || !tideId.trim()) { setMsg('Enter a station ID'); return; }
    if ((settings.tide_stations || []).some((s) => s.id === tideId.trim())) { setMsg('That station is already configured'); return; }
    const tide_stations = [...(settings.tide_stations || []), { id: tideId.trim(), name: tideName.trim() || tideId.trim() }];
    save({ tide_stations }, 'Tide station saved');
    setTideId(''); setTideName('');
  };

  const removeTideStation = (id: string) => {
    if (!settings) return;
    save({ tide_stations: (settings.tide_stations || []).filter((s) => s.id !== id) }, 'Tide station removed');
  };

  const saveToken = () => {
    setWriteToken(token.trim());
    setMsg(token.trim() ? 'Write token stored in this browser' : 'Write token cleared');
  };

  const card = 'bg-slate-900/50 p-6 rounded-xl border border-slate-800';
  const label = 'text-sm text-slate-400 uppercase tracking-wider mb-4';
  const input = 'bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 focus:ring-2 focus:ring-blue-500 outline-none';
  const primary = 'bg-blue-600 hover:bg-blue-500 disabled:opacity-50 px-4 py-2 rounded text-sm font-medium';

  return (
    <div className="space-y-6">
      {msg && (
        <div className="rounded-lg border border-slate-700 bg-slate-900 px-4 py-2 text-sm text-slate-300">{msg}</div>
      )}

      <div className={card}>
        <h2 className={label}>Server write token (only if the server sets SSNOW_API_TOKEN)</h2>
        <div className="flex flex-wrap gap-2">
          <input value={token} onChange={(e) => setToken(e.target.value)} type="password" placeholder="X-SSNOW-Token / Bearer token"
            className={`${input} w-full max-w-sm`} />
          <button onClick={saveToken} className={primary}>Store in browser</button>
        </div>
        <p className="mt-2 text-xs text-slate-500">Kept in this browser only (localStorage). Required for ingest/settings/sim actions when the server is token-protected.</p>
      </div>

      <div className={card}>
        <h2 className={label}>Locations (weather, air quality, marine, aurora verdict, declination)</h2>
        <div className="flex flex-wrap gap-2">
          <input value={locName} onChange={(e) => setLocName(e.target.value)} placeholder="Name" className={input} />
          <input value={locLat} onChange={(e) => setLocLat(e.target.value)} placeholder="Lat" className={`${input} w-24`} />
          <input value={locLon} onChange={(e) => setLocLon(e.target.value)} placeholder="Lon" className={`${input} w-24`} />
          <button onClick={addLocation} disabled={busy} className={primary}>Add</button>
        </div>
        {settings && settings.locations.length > 0 ? (
          <ul className="mt-4 space-y-1 text-sm text-slate-300">
            {settings.locations.map((l) => (
              <li key={l.key} className="flex items-center gap-3">
                <span className="flex-1">{l.name} <span className="text-xs text-slate-500">({l.lat.toFixed(2)}, {l.lon.toFixed(2)})</span></span>
                <button onClick={() => removeLocation(l.key)} disabled={busy}
                  className="text-xs text-slate-400 hover:text-red-400 border border-slate-700 rounded px-2 py-0.5">Remove</button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-4 text-sm text-slate-500">No locations yet — events, weather and the aurora verdict all use the first one.</p>
        )}
      </div>

      <div className={card}>
        <h2 className={label}>Tide stations (NOAA CO-OPS IDs)</h2>
        <div className="flex flex-wrap gap-2">
          <input value={tideId} onChange={(e) => setTideId(e.target.value)} placeholder="Station ID (e.g. 8454000)" className={input} />
          <input value={tideName} onChange={(e) => setTideName(e.target.value)} placeholder="Label" className={input} />
          <button onClick={addTideStation} disabled={busy} className={primary}>Add</button>
        </div>
        {settings && (settings.tide_stations || []).length > 0 ? (
          <ul className="mt-4 space-y-1 text-sm text-slate-300">
            {settings.tide_stations.map((s) => (
              <li key={s.id} className="flex items-center gap-3">
                <span className="flex-1">{s.name} <span className="text-xs text-slate-500">({s.id})</span></span>
                <button onClick={() => removeTideStation(s.id)} disabled={busy}
                  className="text-xs text-slate-400 hover:text-red-400 border border-slate-700 rounded px-2 py-0.5">Remove</button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-4 text-sm text-slate-500">No stations yet.</p>
        )}
        <p className="mt-2 text-xs text-slate-500">Find IDs via NOAA Tides &amp; Currents station search.</p>
      </div>

      <div className={card}>
        <h2 className={label}>NASA API key (optional, for DONKI)</h2>
        <div className="flex flex-wrap items-center gap-2">
          <input value={nasaKey} onChange={(e) => setNasaKey(e.target.value)} type="password" placeholder="Leave blank to keep the stored key"
            className={`${input} w-full max-w-xs`} />
          <button onClick={() => { save({ nasa_api_key: nasaKey || undefined }, nasaKey ? 'NASA key saved' : 'No change'); setNasaKey(''); }}
            disabled={busy} className={primary}>Save key</button>
          <span className={`text-xs ${settings?.nasa_api_key ? 'text-emerald-400' : 'text-slate-500'}`}>
            {settings?.nasa_api_key ? 'key stored on server' : 'no key stored (DEMO_KEY fallback)'}
          </span>
        </div>
      </div>

      <div className={card}>
        <h2 className={label}>Retention</h2>
        <div className="flex flex-wrap items-center gap-2">
          <input value={retention} onChange={(e) => setRetention(e.target.value)} type="number" min={1}
            className={`${input} w-32`} />
          <span className="text-sm text-slate-400">days of raw snapshots</span>
          <button onClick={() => save({ retention_days: parseInt(retention) || 90 }, 'Retention saved')}
            disabled={busy} className={primary}>Save</button>
        </div>
      </div>

      <div className={card}>
        <h2 className={label}>Manual ingest</h2>
        <button onClick={() => { setBusy(true); api.ingest().then(() => setMsg('Ingest complete')).catch((e) => setMsg(String(e))).finally(() => setBusy(false)); }}
          disabled={busy} className={primary}>Run ingestion now</button>
      </div>
    </div>
  );
}
