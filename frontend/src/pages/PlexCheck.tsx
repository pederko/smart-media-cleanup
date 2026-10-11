import { Fragment, useState } from "react";
import { api, qs } from "../api";
import { ago, bytes, fileName, num } from "../format";
import { ErrorNote, useFetch, useOpenTitle, useRefreshTick } from "../components/common";

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
  const { data, error } = useFetch<Resp>(`/api/plex-check${qs({ view, q })}`, [tick]);
  const s = data?.summary;
  const missingView = view === "missing";

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
              <li key={code}><button className="linkish" onClick={() => setView(`reason:${code}`)}>{REASONS[code] ?? code}</button>: {pl(a.groups, "tittel", "titler")}, {bytes(a.size)}</li>
            ))}
          </ul>
          <p className="small muted">Sammenlignet med Plex-bibliotekene {s.sections.join(", ")}, sist hentet {ago(s.plex_synced)}. Ekstramateriale og nedlastingsmappen er ikke tatt med.</p>
        </section>
      )}
      {data?.available && (
        <>
          <div className="toolbar" style={{ marginTop: 24 }}>
            <div className="seg" role="group" aria-label="Visning">
              <button aria-pressed={!missingView} onClick={() => setView("not_in_plex")}>På disk, ikke i Plex{s ? ` (${s.not_in_plex.groups})` : ""}</button>
              <button aria-pressed={missingView} onClick={() => setView("missing")}>I Plex, mangler på disk{s ? ` (${s.missing.groups})` : ""}</button>
            </div>
            <input type="search" placeholder="Søk" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Søk" />
            {view.startsWith("reason:") && <button className="btn small" onClick={() => setView("not_in_plex")}>Vis alle årsaker</button>}
          </div>
          {missingView && <p className="small muted">Plex fjerner disse når biblioteket skannes og papirkurven tømmes (Plex → bibliotek → ⋯ → Empty Trash). Seerhistorikken i Tautulli beholdes.</p>}
          <div className="table-wrap">
            <table>
              <thead><tr><th>Tittel / mappe</th><th>{missingView ? "Plex-bibliotek" : "Årsak"}</th><th className="r">Filer</th><th className="r">Størrelse</th><th /></tr></thead>
              <tbody>
                {data.items.map((g) => (
                  <Fragment key={g.key}>
                    <tr className="row">
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
                        {g.section_key && <button className="btn small" onClick={() => rescan(g)}>Be Plex skanne</button>}
                        {msg[g.key] && <div className="small muted" style={{ maxWidth: 260, marginTop: 4 }}>{msg[g.key]}</div>}
                      </td>
                    </tr>
                    {open === g.key && (
                      <tr className="detail"><td colSpan={5}>
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
    </>
  );
}
