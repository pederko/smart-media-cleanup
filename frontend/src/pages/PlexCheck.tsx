import { Fragment, useState } from "react";
import { api, qs } from "../api";
import { ago, bytes, fileName, num } from "../format";
import { ErrorNote, useFetch, useOpenTitle, useRefreshTick } from "../components/common";
import CleanupDialog from "../components/CleanupDialog";

type Agg = { groups: number; files: number; size: number };
type Group = { key: string; title_key?: string | null; name: string; year?: number | null; library?: string; section: string | null;
  section_key: string | null; folder: string; reason?: string; code?: string; count: number; size: number; newest?: number;
  managed?: boolean; files: { path: string; size: number; reason?: string; label?: string | null }[] };
type Resp = { available: boolean; message?: string; total: number; items: Group[];
  summary: { not_in_plex: Agg; missing: Agg; by_reason: Record<string, Agg>; plex_synced: number | null; sections: string[] } };

const REASONS: Record<string, string> = {
  no_section: "Ikke i noe Plex-bibliotek", disc: "Diskbilder (ISO)", recent: "Nylig lagt til", unmatched: "Ikke funnet av Plex",
};

function pl(n: number, one: string, many: string) { return `${num(n)} ${n === 1 ? one : many}`; }

export default function PlexCheckPage() {
  const tick = useRefreshTick();
  const openTitle = useOpenTitle();
  const [view, setView] = useState("not_in_plex");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [msg, setMsg] = useState<Record<string, string>>({});
  const [reload, setReload] = useState(0);
  const [sel, setSel] = useState<string[]>([]);
  const [dialog, setDialog] = useState<string[] | null>(null);
  const { data, error } = useFetch<Resp>(`/api/plex-check${qs({ view, q })}`, [tick, reload]);
  const s = data?.summary;
  const missingView = view === "missing";
  const mode: "disk" | "plex" = missingView ? "plex" : "disk";
  // på disk: bare titler som verken Radarr eller Sonarr kjenner kan slettes herfra (hele toppmappen)
  const selKey = (g: Group) => missingView ? g.key : (g.title_key?.startsWith("dir:") && !g.managed ? g.title_key : null);
  const switchView = (v: string) => { setView(v); setSel([]); };
  const toggle = (k: string) => setSel(sel.includes(k) ? sel.filter((x) => x !== k) : [...sel, k]);
  const selectable = (data?.items ?? []).map(selKey).filter((k): k is string => !!k);

  const rescan = async (g: Group) => {
    setMsg({ ...msg, [g.key]: "Ber Plex skanne…" });
    try {
      const r = await api.post<{ message: string }>("/api/plex-check/rescan", { folder: g.folder });
      setMsg((m) => ({ ...m, [g.key]: r.message }));
    } catch (e) { setMsg((m) => ({ ...m, [g.key]: String((e as Error).message) })); }
  };

  return (
    <>
      <h1>Plex-avvik</h1>
      <ErrorNote error={error} />
      {data && !data.available && <div className="empty">{data.message}</div>}
      {s && data?.available && (
        <section className="brief">
          <p className="brief-lead">
            {s.not_in_plex.groups > 0
              ? <><b>{pl(s.not_in_plex.groups, "tittel eller mappe", "titler eller mapper")}</b> ({pl(s.not_in_plex.files, "videofil", "videofiler")}, <b>{bytes(s.not_in_plex.size)}</b>) ligger på disk uten å være i Plex.</>
              : <>Alt som ligger på disk, finnes i Plex.</>}{" "}
            {s.missing.files > 0 && <>{pl(s.missing.files, "fil", "filer")} i Plex mangler på disk.</>}
          </p>
          <ul className="brief-points">
            {Object.entries(s.by_reason).sort((a, b) => b[1].size - a[1].size).map(([code, a]) => (
              <li key={code}><button className="linkish" onClick={() => switchView(`reason:${code}`)}>{REASONS[code] ?? code}</button>: {pl(a.groups, "tittel", "titler")}, {bytes(a.size)}</li>
            ))}
          </ul>
          <p className="small muted">Sammenlignet med Plex-bibliotekene {s.sections.join(", ")}, sist hentet {ago(s.plex_synced)}. Ekstramateriale og nedlastingsmappen er ikke tatt med.</p>
        </section>
      )}
      {data?.available && (
        <>
          <div className="toolbar" style={{ marginTop: 24 }}>
            <div className="seg" role="group" aria-label="Visning">
              <button aria-pressed={!missingView} onClick={() => switchView("not_in_plex")}>På disk, ikke i Plex{s ? ` (${s.not_in_plex.groups})` : ""}</button>
              <button aria-pressed={missingView} onClick={() => switchView("missing")}>I Plex, mangler på disk{s ? ` (${s.missing.groups})` : ""}</button>
            </div>
            <input type="search" placeholder="Søk" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Søk" />
            {selectable.length > 0 && <button className="btn small" onClick={() => setSel([...new Set([...sel, ...selectable])])}>Velg alle ({selectable.length})</button>}
            {view.startsWith("reason:") && <button className="btn small" onClick={() => switchView("not_in_plex")}>Vis alle årsaker</button>}
          </div>
          {missingView && <p className="small muted">Plex fjerner disse når biblioteket skannes og papirkurven tømmes (Plex → bibliotek → ⋯ → Empty Trash). Seerhistorikken i Tautulli beholdes.</p>}
          <div className="table-wrap">
            <table>
              <thead><tr><th style={{ width: 28 }} /><th>Tittel / mappe</th><th>{missingView ? "Plex-bibliotek" : "Årsak"}</th><th className="r">Filer</th><th className="r">Størrelse</th><th /></tr></thead>
              <tbody>
                {data.items.map((g) => (
                  <Fragment key={g.key}>
                    <tr className="row">
                      <td>{selKey(g) && <input type="checkbox" checked={sel.includes(selKey(g)!)} onChange={() => toggle(selKey(g)!)} aria-label={`Velg ${g.name}`} />}</td>
                      <td className="title-cell">
                        <button className="btn small linkish" onClick={() => setOpen(open === g.key ? null : g.key)} aria-expanded={open === g.key}>{g.name}{g.year ? ` (${g.year})` : ""}</button>
                        <small className="path">{g.folder}</small>
                        {g.title_key && !g.title_key.startsWith("dir:") && <small><button className="linkish" onClick={() => openTitle(g.title_key!)}>Åpne tittel</button></small>}
                        {g.title_key?.startsWith("dir:") && <small><button className="linkish" onClick={() => openTitle(g.title_key!)}>Vis filer</button>{g.managed ? "" : ", ikke i Radarr/Sonarr"}</small>}
                      </td>
                      <td className="small">{missingView ? g.section : <>{g.reason}{g.newest ? <div className="muted">endret {ago(g.newest)}</div> : null}</>}</td>
                      <td className="r">{g.count}</td>
                      <td className="r num">{bytes(g.size)}</td>
                      <td className="r">
                        <div style={{ display: "flex", gap: 6, justifyContent: "flex-end", flexWrap: "wrap" }}>
                          {g.section_key && !missingView && <button className="btn small" onClick={() => rescan(g)}>Be Plex skanne</button>}
                          {selKey(g) && <button className="btn small" onClick={() => setDialog([selKey(g)!])}>{missingView ? "Fjern fra Plex…" : "Slett fra disk…"}</button>}
                        </div>
                        {!missingView && g.managed && <div className="small muted" style={{ marginTop: 4 }}>Slett via tittelen (Radarr/Sonarr)</div>}
                        {msg[g.key] && <div className="small muted" style={{ maxWidth: 260, marginTop: 4 }}>{msg[g.key]}</div>}
                      </td>
                    </tr>
                    {open === g.key && (
                      <tr className="detail"><td colSpan={6}>
                        <table className="compact"><tbody>
                          {g.files.map((f) => <tr key={f.path}><td>{f.label ? `${f.label} ` : ""}{fileName(f.path)}</td><td className="small muted">{f.reason ?? ""}</td><td className="r num">{bytes(f.size)}</td></tr>)}
                        </tbody></table>
                      </td></tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
          {data.items.length === 0 && <div className="empty">Ingen avvik i dette utvalget.</div>}
        </>
      )}
      {sel.length > 0 && (
        <div className="tray" role="region" aria-label="Valgte">
          <div><div className="big">{pl(sel.length, "valgt", "valgte")}</div><div className="small muted">{missingView ? "fjernes fra Plex" : "slettes fra disk"}</div></div>
          <div className="grow" />
          <button className="btn" onClick={() => setSel([])}>Tøm utvalget</button>
          <button className="btn danger" onClick={() => setDialog(sel)}>{missingView ? "Fjern fra Plex…" : "Slett fra disk…"}</button>
        </div>
      )}
      {dialog && <CleanupDialog mode={mode} keys={dialog} onClose={() => setDialog(null)} onDone={() => { setSel([]); setReload((r) => r + 1); }} />}
    </>
  );
}
