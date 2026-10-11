import { useEffect, useState } from "react";
import { api } from "../api";
import { ago, bytes } from "../format";
import { t } from "../i18n";
import { useOpenTitle } from "./common";

export type Swap = { id: number; created: number; updated: number; title_key: string; title: string; service: string;
  season: number | null; release_title: string; release_size: number; old_size: number; after_swap: string;
  state: string; message: string; progress: number | null; log: { ts: number; state: string; message: string }[] };

export const ACTIVE = ["waiting", "downloading", "ready", "importing"];

export function swapState(state: string): [string, string] {
  return (({
    waiting: [t("Waiting", "Venter"), "risk-medium"], downloading: [t("Downloading", "Laster ned"), "risk-medium"],
    ready: [t("Ready to swap", "Klar til bytte"), "risk-medium"], importing: [t("Importing", "Importerer"), "risk-medium"],
    done: [t("Done", "Ferdig"), "risk-low"], failed: [t("Failed", "Feilet"), "risk-high"],
    needs_help: [t("Needs help", "Trenger hjelp"), "risk-high"], cancelled: [t("Cancelled", "Avbrutt"), ""],
  } as Record<string, [string, string]>)[state] ?? [state, ""]);
}

/** Signal from the release search that a swap was started. */
export const swapsChanged = () => window.dispatchEvent(new Event("smc-swaps"));

/** Swaps – for one title or all. Follows up active swaps while it is open. */
export default function SwapList({ titleKey, empty }: { titleKey?: string; empty?: string }) {
  const [items, setItems] = useState<Swap[] | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const openTitle = useOpenTitle();
  const load = async () => {
    try {
      const r = await api.get<{ items: Swap[] }>(`/api/swaps${titleKey ? `?key=${encodeURIComponent(titleKey)}` : ""}`);
      setItems(r.items);
      return r.items;
    } catch { return []; }
  };
  useEffect(() => {
    let alive = true;
    load();
    const onChange = () => { if (alive) load(); };
    window.addEventListener("smc-swaps", onChange);
    const iv = setInterval(async () => {
      const cur = await load();
      for (const s of cur.filter((x) => ACTIVE.includes(x.state))) {
        try { await api.post(`/api/swaps/${s.id}/poll`); } catch { /* retried next time */ }
      }
      if (cur.some((x) => ACTIVE.includes(x.state))) load();
    }, 15000);
    return () => { alive = false; clearInterval(iv); window.removeEventListener("smc-swaps", onChange); };
  }, [titleKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const cancel = async (id: number) => { await api.post(`/api/swaps/${id}/cancel`); load(); };
  if (!items) return null;
  if (items.length === 0) return empty ? <p className="muted small">{empty}</p> : null;
  return (
    <div className="table-wrap">
      <table className="compact">
        <thead><tr><th>{titleKey ? t("Swap", "Bytte") : t("Title", "Tittel")}</th><th>{t("Status", "Status")}</th><th className="r">{t("Before → after", "Før → etter")}</th><th>{t("Updated", "Oppdatert")}</th><th /></tr></thead>
        <tbody>
          {items.map((s) => {
            const [label, cls] = swapState(s.state);
            const active = ACTIVE.includes(s.state);
            return (
              <tr key={s.id}>
                <td style={{ maxWidth: 360 }}>
                  {!titleKey && <div><button className="linkish" onClick={() => openTitle(s.title_key)}>{s.title}</button>{s.season != null ? t(`, season ${s.season}`, `, sesong ${s.season}`) : ""}</div>}
                  {titleKey && s.season != null && <div>{t("Season", "Sesong")} {s.season}</div>}
                  <div className="small muted" style={{ wordBreak: "break-word" }}>{s.release_title}</div>
                </td>
                <td style={{ minWidth: 200 }}>
                  <span className={`pill ${cls}`}>{label}</span>
                  {s.state === "downloading" && s.progress != null && <div className="progress" style={{ marginTop: 6 }}><i style={{ width: `${s.progress * 100}%` }} /></div>}
                  <div className="small muted" style={{ marginTop: 4 }}>{s.message}</div>
                  {s.log.length > 1 && <button className="linkish small" onClick={() => setOpen(open === s.id ? null : s.id)}>{open === s.id ? t("Hide history", "Skjul historikk") : t("History", "Historikk")}</button>}
                  {open === s.id && <ul className="small muted" style={{ paddingLeft: 16, margin: "4px 0" }}>{s.log.map((l, i) => <li key={i}>{ago(l.ts)}: {l.message}</li>)}</ul>}
                </td>
                <td className="r num small">{bytes(s.old_size)} → {bytes(s.release_size)}</td>
                <td className="small muted">{ago(s.updated)}</td>
                <td className="r">{active && <button className="btn small" onClick={() => cancel(s.id)}>{t("Cancel", "Avbryt")}</button>}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
