export interface Event {
  id: string;
  source: string;
  upstream_id: string;
  category: string;
  title: string;
  description: string | null;
  occurred_at: string | null;
  updated_at: string | null;
  latitude: number | null;
  longitude: number | null;
  depth_km: number | null;
  magnitude: number | null;
  magnitude_unit: string | null;
  url: string | null;
  raw_ref: string | null;
  ingested_at: string | null;
  extra: Record<string, unknown>;
}

export interface SourceState {
  source_id: string;
  name: string;
  domain: string;
  attribution: string;
  license: string;
  cadence_seconds: number | null;
  enabled: boolean;
  last_attempt: string | null;
  last_success: string | null;
  last_error: string | null;
  consecutive_failures: number;
  next_due: string | null;
  records_ingested: number;
}

export interface Stats {
  events: number;
  observations: number;
  snapshots: number;
  snapshot_bytes: number;
  assets: number;
  asset_bytes: number;
  db_bytes: number;
  snapshots_dir: string;
  assets_dir: string;
  db_path: string;
}

export interface KpPoint {
  ts: string;
  value: number;
  estimated: boolean;
}

export interface MoonState {
  phase_name: string | null;
  illumination: number | null;
  distance_km: number | null;
  source: string | null;
  computed_at: string | null;
  rise_utc: string | null;
  set_utc: string | null;
  next_rise_utc: string | null;
  next_set_utc: string | null;
}

export interface SimScenario {
  id: string;
  title: string;
  description: string;
  citation: string;
  params: Array<{
    id: string;
    label: string;
    type: string;
    unit: string | null;
    default: any;
    min: number | null;
    max: number | null;
    options: Array<{ label: string; value: string }> | null;
  }>;
  output_labels: Record<string, string>;
}

export interface Settings {
  locations: Array<{ name: string; lat: number; lon: number; key: string }>;
  tide_stations: Array<{ id: string; name: string }>;
  nasa_api_key: boolean;
  retention_days: number;
}

export interface SunSummary {
  kp: { value: number; ts: string } | null;
  kp_forecast: Array<{ ts: string; value: number }>;
  xray: { value: number; ts: string; class: string } | null;
  f107: { value: number; ts: string } | null;
  aurora_max: { value: number; ts: string } | null;
  bz_gsm: { value: number; ts: string; spacecraft?: string } | null;
  bt: { value: number; ts: string } | null;
  dst: { value: number; ts: string } | null;
  proton_gte10: { value: number; ts: string } | null;
  proton_gte50: { value: number; ts: string } | null;
  proton_gte100: { value: number; ts: string } | null;
  wind_speed: { value: number; ts: string } | null;
  wind_density: { value: number; ts: string } | null;
  aurora_oval: { value: number; ts: string } | null;
  aurora_mean: { value: number; ts: string } | null;
  declination: { value: number; ts: string; location: string } | null;
  ssn: { value: number; ts: string } | null;
  ssn_predicted: { value: number; ts: string } | null;
}

const API = "/api";

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, init);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export const api = {
  health: () => json<{ status: string; service: string }>("/health"),
  stats: () => json<Stats>("/stats"),
  sources: () => json<{ sources: SourceState[] }>("/sources"),
  events: (params?: {
    start?: string; end?: string; categories?: string; min_magnitude?: number; limit?: number;
  }) => {
    const qs = new URLSearchParams();
    if (params?.start) qs.set("start", params.start);
    if (params?.end) qs.set("end", params.end);
    if (params?.categories) qs.set("categories", params.categories);
    if (params?.min_magnitude != null) qs.set("min_magnitude", String(params.min_magnitude));
    if (params?.limit != null) qs.set("limit", String(params.limit));
    return json<{ count: number; events: Event[] }>(`/events?${qs.toString()}`);
  },
  event: (id: string) => json<Event>(`/events/${encodeURIComponent(id)}`),
  kp: (limit?: number) => json<{ series: string; unit: string; count: number; points: KpPoint[] }>(`/sun/kp?limit=${limit ?? 120}`),
  moon: () => json<MoonState>("/moon/state"),
  ingest: () => json<{ timestamp: string; sources: any[] }>("/ingest", { method: "POST" }),
  settings: {
    get: () => json<Settings>("/settings"),
    set: (body: Partial<Settings> & { nasa_api_key?: string }) => json<{ ok: boolean }>("/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  },
  simScenarios: () => json<{ scenarios: SimScenario[] }>("/sim/scenarios"),
  simRun: (body: { id: string; params: Record<string, any> }) =>
    json<any>("/sim/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  sunSummary: () => json<SunSummary>("/sun/summary"),
  obs: (source: string, series: string, limit?: number) =>
    json<{ source: string; series: string; unit: string | null; count: number; points: Array<{ ts: string; value: number; extra: any }> }>(`/obs?source=${encodeURIComponent(source)}&series=${encodeURIComponent(series)}&limit=${limit ?? 120}`),
  neos: (limit?: number) =>
    json<{ count: number; pha: number; inside_moon: number; comets: number; neos: Array<{ id: string; name: string; kind: string; is_comet: boolean; hazardous: boolean; approach_at: string | null; dist_lunar: number | null; dist_km: number | null; velocity_km_s: number | null; h: number | null; diameter_km: number | null; url: string | null; source: string }> }>(`/neos?limit=${limit ?? 200}`),
  spcOutlooks: (limit?: number) =>
    json<{ count: number; outlooks: Event[] }>(`/spc/outlooks?limit=${limit ?? 50}`),
  fireballs: (limit?: number) =>
    json<{ count: number; fireballs: Event[] }>(`/fireballs?limit=${limit ?? 100}`),
  sunImages: () =>
    json<{ channels: Record<string, string> }>(`/sun/images`),
  cmeWatch: () =>
    json<{ available: boolean; simulation?: boolean; cme_id?: string; cme_time?: string | null; cme_speed_km_s?: number; flare_class?: string; result?: { arrival_window_low_hours: number; arrival_window_high_hours: number; arrival_utc: string; storm_proxy: string }; reason?: string }>(`/sim/cme-watch`),
};
