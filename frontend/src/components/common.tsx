import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { api, Component, Suggestion } from "../api";
import { ago, bytes, date } from "../format";

export function useFetch<T>(url: string | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const seq = useRef(0);
  const load = useCallback(() => {
    if (!url) return;
    const n = ++seq.current;
    setLoading(true);
    api.get<T>(url)
      .then((d) => { if (n === seq.current) { setData(d); setError(null); } })
      .catch((e) => { if (n === seq.current) setError(String(e.message ?? e)); })
      .finally(() => { if (n === seq.current) setLoading(false); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, ...deps]);
  useEffect(load, [load]);
  return { data, error, loading, reload: load };
}

/** Oppdateres når en jobb blir ferdig, slik at sidene henter ferske tall. */
export const RefreshContext = createContext(0);
export const useRefreshTick = () => useContext(RefreshContext);

export const TitleContext = createContext<(key: string) => void>(() => {});
export const useOpenTitle = () => useContext(TitleContext);

export function RiskPill({ risk }: { risk: string }) {
  return <span className={`pill risk-${risk}`}>{risk === "høy" ? "Høy risiko" : risk === "middels" ? "Middels risiko" : "Lav risiko"}</span>;
}

export function ScoreMeter({ score }: { score: number }) {
  return (
    <div className="score" title={`Prioritet ${score} av 100`}>
      <b>{Math.round(score)}</b>
      <div className="meter"><i style={{ width: `${Math.max(2, Math.min(100, score))}%` }} /></div>
    </div>
  );
}

export function Breakdown({ components, score }: { components: Component[]; score: number }) {
  const sorted = [...components].sort((a, b) => b.points - a.points);
  const raw = components.reduce((s, c) => s + c.points, 0);
  return (
    <div>
      {sorted.map((c, i) => (
        <div className="comp" key={i}>
          <span className={`p ${c.points > 0 ? "plus" : c.points < 0 ? "minus" : "zero"}`}>
            {c.points > 0 ? "+" : ""}{c.points.toLocaleString("nb-NO")}
          </span>
          <span>{c.label}<small>{c.detail}</small></span>
        </div>
      ))}
      <div className="comp total">
        <span className="p">{Math.round(score)}</span>
        <span>Prioritet{raw !== score && <small>Summen {raw.toLocaleString("nb-NO", { maximumFractionDigits: 1 })} er avgrenset til 0–100</small>}</span>
      </div>
    </div>
  );
}

export function HistoryLine({ h }: { h: Suggestion["history"] }) {
  if (!h || h.plays == null) return <span className="muted">Ingen seerdata</span>;
  if (!h.plays) return <span>Aldri sett{h.history_start ? ` siden ${date(h.history_start)}` : ""}</span>;
  return (
    <span>
      {h.plays} avspilling{h.plays === 1 ? "" : "er"}, sist {ago(h.last_played)}
      {h.users && h.users.length > 0 && <span className="muted">, {h.users.length} bruker{h.users.length === 1 ? "" : "e"}</span>}
    </span>
  );
}

export function RequestedBy({ requests }: { requests?: { by: string; at: number | null; watched: boolean }[] }) {
  if (!requests || requests.length === 0) return null;
  const names = [...new Set(requests.map((r) => r.by))];
  const notSeen = requests.filter((r) => !r.watched).map((r) => r.by);
  return (
    <span className="req" title={requests.map((r) => `${r.by}, ${date(r.at)}${r.watched ? " (har sett den)" : " (har ikke sett den)"}`).join("\n")}>
      Etterspurt av {names.join(", ")}{notSeen.length === requests.length ? (names.length === 1 ? ", som ikke har sett den" : ", ingen av dem har sett den") : ""}
    </span>
  );
}

export function Savings({ s }: { s: Suggestion }) {
  return (
    <span className="num" title={s.savings_note || undefined}>
      {bytes(s.savings)}{s.savings_note && <span className="faint"> *</span>}
    </span>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function ErrorNote({ error }: { error: string | null }) {
  if (!error) return null;
  return <div className="notice err">Kunne ikke hente data: {error}</div>;
}
