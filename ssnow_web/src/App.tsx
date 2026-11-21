import React, { useEffect, useState } from 'react';
import { LayoutDashboard, List, Map, Sun, Moon, Rocket, Cloud, Settings as SettingsIcon } from 'lucide-react';
import Dashboard from './views/Dashboard';
import Events from './views/Events';
import MapView from './views/MapView';
import SimView from './views/SimView';
import SunView from './views/SunView';
import MoonView from './views/MoonView';
import NeoView from './views/NeoView';
import StreamOverlay from './views/StreamOverlay';
import Sources from './views/Sources';
import Settings from './views/Settings';

const TABS: { id: string; label: string; icon: React.ElementType }[] = [
  { id: 'dashboard', label: 'Now', icon: LayoutDashboard },
  { id: 'events', label: 'Events', icon: List },
  { id: 'map', label: 'Map', icon: Map },
  { id: 'sun', label: 'Sun', icon: Sun },
  { id: 'moon', label: 'Moon', icon: Moon },
  { id: 'neos', label: 'Asteroids', icon: Rocket },
  { id: 'sim', label: 'Simulation', icon: Sun },
  { id: 'sources', label: 'Sources', icon: Cloud },
  { id: 'settings', label: 'Settings', icon: SettingsIcon },
];

const VIEWS: Record<string, React.ElementType> = {
  dashboard: Dashboard,
  events: Events,
  map: MapView,
  sun: SunView,
  moon: MoonView,
  neos: NeoView,
  sim: SimView,
  sources: Sources,
  settings: Settings,
};

export default function App() {
  // OBS Browser Source target: chrome-free broadcast overlay.
  if (window.location.pathname.replace(/\/+$/, '') === '/stream') {
    return <StreamOverlay />;
  }
  return <DashboardShell />;
}

function DashboardShell() {
  const [tab, setTab] = useState('dashboard');
  const [refreshKey, setRefreshKey] = useState(0);
  const [live, setLive] = useState(false);

  // SSE live stream: server pushes ingest_complete + heartbeat.
  // EventSource reconnects natively; any successful message = connected.
  // ?nosse=1 skips the stream (static embeds, headless capture).
  useEffect(() => {
    if (new URLSearchParams(window.location.search).get('nosse') === '1') return;
    const src = new EventSource('/api/stream/live');
    src.onmessage = (ev) => {
      setLive(true);
      try {
        if (JSON.parse(ev.data)?.type === 'ingest_complete') setRefreshKey((k) => k + 1);
      } catch { /* heartbeat / non-JSON: ignore */ }
    };
    src.onerror = () => setLive(false);
    return () => src.close();
  }, []);
  return (
    <div className="flex h-screen overflow-hidden">
      <aside className="w-60 bg-slate-900 border-r border-slate-800 flex flex-col">
        <div className="p-4 flex items-center gap-2 border-b border-slate-800">
          <div className="w-6 h-6 rounded bg-blue-500 flex items-center justify-center">
            <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21-3.582-4-8-4S0 4.79 0 7z"/></svg>
          </div>
          <span className="font-bold text-xl tracking-tight">Solar System Now</span>
        </div>
        <nav className="flex-1 overflow-y-auto p-2 space-y-1">
          {TABS.map((t) => {
            const Icon = t.icon;
            const active = tab === t.id;
            return (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition ${
                  active
                    ? 'bg-blue-600/20 text-blue-300 border border-blue-500/30'
                    : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
                }`}
              >
                <Icon className="w-4 h-4" />
                {t.label}
              </button>
            );
          })}
        </nav>
        <div className="p-4 text-xs text-slate-500 border-t border-slate-800">
          Web GUI · Phase 2<br />
          FastAPI + React
        </div>
      </aside>
      <main className="flex-1 overflow-hidden flex flex-col bg-slate-950">
        <header className="h-12 border-b border-slate-800 flex items-center justify-between px-4">
          <h1 className="text-lg font-semibold">{TABS.find((t) => t.id === tab)?.label}</h1>
          <div className="flex items-center gap-2">
            <span
              title={live ? 'Live stream connected — views auto-refresh on ingest' : 'Live stream offline'}
              className={`px-2 py-1 text-xs rounded border ${live ? 'text-emerald-300 border-emerald-700 bg-emerald-950/50' : 'text-slate-500 border-slate-700'}`}
            >
              {live ? '● LIVE' : '○ offline'}
            </span>
            <button
              className="px-3 py-1 text-xs bg-slate-800 hover:bg-slate-700 active:bg-slate-600 rounded text-slate-200 border border-slate-700 cursor-pointer"
              onClick={() => setRefreshKey((k) => k + 1)}
            >
              Refresh
            </button>
          </div>
        </header>
        <div className="flex-1 overflow-auto p-6">
          {VIEWS[tab] ? React.createElement(VIEWS[tab] as any, { key: `${tab}-${refreshKey}`, refreshKey }) : <div>No view</div>}
        </div>
      </main>
    </div>
  );
}
