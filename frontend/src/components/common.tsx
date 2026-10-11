import { createContext, ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";
import { api, Component, Status, Suggestion } from "../api";
import { ago, bytes, date } from "../format";
import { plural, t } from "../i18n";

// ------------------------------------------------------------------ data

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

/** Bumped when a job finishes, so the pages fetch fresh numbers. */
export const RefreshContext = createContext(0);
export const useRefreshTick = () => useContext(RefreshContext);

/** Opens the title panel. */
export const TitleContext = createContext<(key: string) => void>(() => {});
export const useOpenTitle = () => useContext(TitleContext);

/** /api/status, polled once by the app shell and shared with every page. */
export const StatusContext = createContext<Status | null>(null);
export const useStatus = () => useContext(StatusContext);

// ------------------------------------------------------------------ page structure

export function PageHeader({ title, lede, children }: { title: string; lede?: ReactNode; children?: ReactNode }) {
  return (
    <header className="page-head">
      <div>
        <h1>{title}</h1>
        {lede && <p className="lede">{lede}</p>}
      </div>
      {children && <div className="page-actions">{children}</div>}
    </header>
  );
}

export function Seg<T extends string>({ value, options, onChange, label }: {
  value: T; options: { value: T; label: ReactNode }[]; onChange: (v: T) => void; label: string;
}) {
  return (
    <div className="seg wrap" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} aria-pressed={value === o.value} onClick={() => onChange(o.value)}>{o.label}</button>
      ))}
    </div>
  );
}

/** The bar at the bottom of the window that shows what is selected and what can be done with it. */
export function Tray({ figure, note, children }: { figure: ReactNode; note: ReactNode; children: ReactNode }) {
  return (
    <div className="tray" role="region" aria-label={t("Selection", "Utvalg")}>
      <div><div className="big">{figure}</div><div className="small muted">{note}</div></div>
      <div className="grow" />
      {children}
    </div>
  );
}

/** Side panel used for the title and for every confirmation. */
export function Drawer({ label, onClose, busy, children, wide }: { label: string; onClose: () => void; busy?: boolean; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && !busy && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose, busy]);
  return (
    <>
      <div className="drawer-bg" onClick={() => !busy && onClose()} />
      <aside className={`drawer${wide ? " wide" : ""}`} role="dialog" aria-modal="true" aria-label={label}>
        <button className="btn small close" onClick={onClose} disabled={busy}>{t("Close", "Lukk")}</button>
        {children}
      </aside>
    </>
  );
}

/** Shown in a confirmation when the needed switch under Settings → Deletion is off. */
export function SwitchedOff({ what, onClose }: { what: "services" | "files"; onClose?: () => void }) {
  return (
    <div className="notice">
      {what === "services"
        ? t("Changes through Radarr, Sonarr, Plex, Seerr and qBittorrent are switched off.", "Endringer via Radarr, Sonarr, Plex, Seerr og qBittorrent er slått av.")
        : t("Deleting files on disk is switched off.", "Sletting av filer på disk er slått av.")}{" "}
      <a href="#/settings/deletion" onClick={onClose}>{t("Switch it on under Settings → Deletion", "Slå det på under Innstillinger → Sletting")}</a>
      {what === "files" && <>{" "}{t("and remove :ro from the folder in the app's compose file.", "og fjern :ro på mappen i appens compose-fil.")}</>}
    </div>
  );
}

export type Result = { status: string; detail: string | null };

export function StatusDot({ status }: { status: string }) {
  return <i className={`dot ${status === "done" ? "ok" : status === "failed" ? "bad" : "off"}`} />;
}

export function statusLabel(s: string) {
  return ({ done: t("Done", "Utført"), failed: t("Failed", "Feilet"), skipped: t("Skipped", "Hoppet over") } as Record<string, string>)[s] ?? s;
}

// ------------------------------------------------------------------ small pieces

export function RiskPill({ risk }: { risk: string }) {
  return <span className={`pill risk-${risk}`}>{risk === "high" ? t("High risk", "Høy risiko") : risk === "medium" ? t("Medium risk", "Middels risiko") : t("Low risk", "Lav risiko")}</span>;
}

export function ScoreMeter({ score }: { score: number }) {
  return (
    <div className="score" title={t(`Priority ${score} of 100`, `Prioritet ${score} av 100`)}>
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
          <span className={`p ${c.points > 0 ? "plus" : c.points < 0 ? "minus" : "zero"}`}>{c.points > 0 ? "+" : ""}{c.points}</span>
          <span>{c.label}<small>{c.detail}</small></span>
        </div>
      ))}
      <div className="comp total">
        <span className="p">{Math.round(score)}</span>
        <span>{t("Priority", "Prioritet")}{Math.abs(raw - score) > 0.05 && <small>{t(`The sum ${raw.toFixed(1)} is capped to 0–100`, `Summen ${raw.toFixed(1)} er avgrenset til 0–100`)}</small>}</span>
      </div>
    </div>
  );
}

export function HistoryLine({ h }: { h: Suggestion["history"] }) {
  if (!h || h.plays == null) return <span className="muted">{t("No watch data", "Ingen seerdata")}</span>;
  if (!h.plays) return <span>{t("Never watched", "Aldri sett")}{h.history_start ? t(` since ${date(h.history_start)}`, ` siden ${date(h.history_start)}`) : ""}</span>;
  return (
    <span>
      {plural(h.plays, ["play", "plays"], ["avspilling", "avspillinger"])}, {t("last", "sist")} {ago(h.last_played)}
      {h.users && h.users.length > 0 && <span className="muted">, {plural(h.users.length, ["user", "users"], ["bruker", "brukere"])}</span>}
    </span>
  );
}

/** Poster from Plex (through the app). A placeholder with the first letter if there is none. */
export function Poster({ k, title, size = "s" }: { k: string | null | undefined; title: string; size?: "s" | "m" | "l" }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [k]);
  if (!k || failed) return <span className={`poster ${size} ph`} aria-hidden="true">{(title || "?").trim().charAt(0).toUpperCase()}</span>;
  return <img className={`poster ${size}`} src={`/api/poster/${encodeURIComponent(k)}`} alt="" loading="lazy" decoding="async" onError={() => setFailed(true)} />;
}

export function RequestedBy({ requests }: { requests?: { by: string; at: number | null; watched: boolean }[] }) {
  if (!requests || requests.length === 0) return null;
  const names = [...new Set(requests.map((r) => r.by))];
  const allUnseen = requests.every((r) => !r.watched);
  const tip = requests.map((r) => `${r.by}, ${date(r.at)}${r.watched ? t(" (has watched it)", " (har sett den)") : t(" (has not watched it)", " (har ikke sett den)")}`).join("\n");
  return (
    <span className="req" title={tip}>
      {t("Requested by", "Etterspurt av")} {names.join(", ")}
      {allUnseen ? (names.length === 1 ? t(", who has not watched it", ", som ikke har sett den") : t(", none of them have watched it", ", ingen av dem har sett den")) : ""}
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

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function Loading() {
  return <p className="muted">{t("Loading…", "Henter…")}</p>;
}

export function ErrorNote({ error }: { error: string | null }) {
  if (!error) return null;
  return <div className="notice err">{t("Could not fetch data:", "Kunne ikke hente data:")} {error}</div>;
}
