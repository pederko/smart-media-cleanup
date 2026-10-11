import { getLang } from "./i18n";

export type Risk = "low" | "medium" | "high";
export type Component = { key: string; label: string; points: number; detail: string };

export type Suggestion = {
  id: string;
  kind: string;
  title_key: string | null;
  scope: string;
  action: string;          // delete | replace | remove
  label: string;           // what to do, e.g. «Delete the movie»
  name: string | null;     // what it is about (title, file or folder)
  location: string;
  score: number;
  risk: Risk;
  size: number;
  savings: number;
  savings_note: string;
  reasons: string[];
  consequences: string[];
  components: Component[];
  history: { plays?: number; last_played?: number | null; users?: string[]; recent_users?: string[]; history_start?: number | null };
  title_name: string | null;
  year: number | null;
  title_kind: string | null;
  library: string | null;
  monitored: number | null;
  best_resolution: string | null;
  radarr_id: number | null;
  sonarr_id: number | null;
  requested_by: string | null;
  requested_at: number | null;
  requests: Request[];
};

export type Request = { by: string; plex_username: string | null; at: number | null; watched: boolean };

export type Requester = { name: string; titles: number; bytes: number; not_watched_by_requester: number;
  not_watched_bytes: number; never_watched: number; never_watched_bytes: number; last_request: number };

export type SuggestionDetail = Suggestion & {
  files: { path: string; claim: number; size: number; alloc: number; nlink: number; mtime: number; season: number | null; episode: number | null; is_extra: number }[];
  overlaps: { id: string; label: string; name: string | null; kind: string; action: string }[];
};

export type Savings = { freed: number; held: number; count: number; files: number; naive_sum?: number; by_library?: Record<string, number> };

export type Job = { id: number; kind: string; status: string; progress: number; message: string; started: number | null;
  finished: number | null; error: string | null; log: string | null };

export type Status = {
  version: string; read_only: boolean; actions_enabled: boolean; files_enabled: boolean; writable: Record<string, boolean>;
  services: Record<string, { ok: boolean; configured?: boolean; message?: string; checked?: number; last_success?: number | null; count?: number | null }>;
  last_sync: number | null; last_scan: { time: number; files: number; bytes: number; duration: number; full: boolean; missing: string[]; stat_calls: number } | null;
  last_analysis: { time: number; suggestions: number } | null; libraries: number; running: Job[]; active_swaps: number;
};

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, { ...init, headers: { "Content-Type": "application/json", "X-Lang": getLang(), ...(init?.headers ?? {}) } });
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try {
      const j = await r.json();
      if (j.detail) msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch { /* ignore */ }
    throw new Error(msg);
  }
  return r.json() as Promise<T>;
}

export const api = {
  get: <T,>(url: string) => req<T>(url),
  post: <T,>(url: string, body?: unknown) => req<T>(url, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) }),
  put: <T,>(url: string, body: unknown) => req<T>(url, { method: "PUT", body: JSON.stringify(body) }),
};

export function qs(params: Record<string, string | number | boolean | undefined | null>) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "" && v !== false) p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
}
