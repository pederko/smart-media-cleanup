export type Component = { key: string; label: string; points: number; detail: string };

export type Suggestion = {
  id: string;
  kind: string;
  title_key: string | null;
  scope: string;
  action: string;
  label: string;
  location: string;
  score: number;
  risk: "lav" | "middels" | "høy";
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
  overlaps: { id: string; label: string; kind: string; action: string }[];
};

export type Savings = { freed: number; held: number; count: number; files: number; naive_sum?: number };

export type Job = { id: number; kind: string; status: string; progress: number; message: string; started: number | null; finished: number | null; error: string | null; log: string | null };

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, { headers: { "Content-Type": "application/json" }, ...init });
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try {
      const j = await r.json();
      if (j.detail) msg = String(j.detail);
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

export function qs(params: Record<string, string | number | undefined | null>) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
}
