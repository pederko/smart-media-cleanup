import { Fragment, useState } from "react";
import { api, qs } from "../api";
import { ago, bytes, fileName } from "../format";
import { plural, t } from "../i18n";
import { ErrorNote, PageHeader, Seg, Tray, useFetch, useOpenTitle, useRefreshTick } from "../components/common";
import CleanupDialog from "../components/CleanupDialog";

type Agg = { groups: number; files: number; size: number };
type Group = { key: string; title_key?: string | null; name: string; year?: number | null; library?: string; section: string | null;
  section_key: string | null; folder: string; reason?: string; code?: string; count: number; size: number; newest?: number;
  managed?: boolean; files: { path: string; size: number; reason?: string; label?: string | null }[] };
type Resp = { available: boolean; message?: string; total: number; items: Group[];
  summary: { not_in_plex: Agg; missing: Agg; by_reason: Record<string, Agg>; plex_synced: number | null; sections: string[] } };

const reasonText = (code: string) => ({
  no_section: t("Not in any Plex library", "Ikke i noe Plex-bibliotek"), disc: t("Disc images (ISO)", "Diskbilder (ISO)"),
  recent: t("Recently added", "Nylig lagt til"), unmatched: t("Not found by Plex", "Ikke funnet av Plex"),
} as Record<string, string>)[code] ?? code;

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
  // On disk: only titles neither Radarr nor Sonarr knows can be deleted from here (the whole top folder)
  const selKey = (g: Group) => missingView ? g.key : (g.title_key?.startsWith("dir:") && !g.managed ? g.title_key : null);
  const switchView = (v: string) => { setView(v); setSel([]); };
  const toggle = (k: string) => setSel(sel.includes(k) ? sel.filter((x) => x !== k) : [...sel, k]);
  const selectable = (data?.items ?? []).map(selKey).filter((k): k is string => !!k);
  const items = (n: number) => plural(n, ["title or folder", "titles or folders"], ["tittel eller mappe", "titler eller mapper"]);

  const rescan = async (g: Group) => {
    setMsg({ ...msg, [g.key]: t("Asking Plex to scan…", "Ber Plex skanne…") });
    try {
      const r = await api.post<{ message: string }>("/api/plex-check/rescan", { folder: g.folder });
      setMsg((m) => ({ ...m, [g.key]: r.message }));
    } catch (e) { setMsg((m) => ({ ...m, [g.key]: String((e as Error).message) })); }
  };

  return (
    <>
      <PageHeader title={t("Plex differences", "Plex-avvik")}
        lede={t("Compares what is on disk with what Plex knows. Files Plex has not picked up can be rescanned or deleted, and Plex entries whose files are gone can be removed.",
          "Sammenligner det som ligger på disk med det Plex kjenner. Filer Plex ikke har fått med seg kan skannes på nytt eller slettes, og Plex-oppføringer uten filer kan fjernes.")} />
      <ErrorNote error={error} />
      {data && !data.available && <div className="empty">{data.message}</div>}
      {s && data?.available && (
        <section className="brief">
          <p className="brief-lead">
            {s.not_in_plex.groups > 0
              ? <><b>{items(s.not_in_plex.groups)}</b> ({plural(s.not_in_plex.files, ["video file", "video files"], ["videofil", "videofiler"])}, <b>{bytes(s.not_in_plex.size)}</b>) {t("are on disk without being in Plex.", "ligger på disk uten å være i Plex.")}</>
              : t("Everything on disk is in Plex.", "Alt som ligger på disk, finnes i Plex.")}{" "}
            {s.missing.files > 0 && `${plural(s.missing.files, ["file in Plex is", "files in Plex are"], ["fil i Plex mangler", "filer i Plex mangler"])} ${t("missing on disk.", "på disk.")}`}
          </p>
          <ul className="brief-points">
            {Object.entries(s.by_reason).sort((a, b) => b[1].size - a[1].size).map(([code, a]) => (
              <li key={code}><button className="linkish" onClick={() => switchView(`reason:${code}`)}>{reasonText(code)}</button>: {plural(a.groups, ["title", "titles"], ["tittel", "titler"])}, {bytes(a.size)}</li>
            ))}
          </ul>
          <p className="small muted">{t(`Compared with the Plex libraries ${s.sections.join(", ")}, last fetched ${ago(s.plex_synced)}. Extras and the downloads folder are left out.`,
            `Sammenlignet med Plex-bibliotekene ${s.sections.join(", ")}, sist hentet ${ago(s.plex_synced)}. Ekstramateriale og nedlastingsmappen er ikke tatt med.`)}</p>
        </section>
      )}
      {data?.available && (
        <>
          <div className="toolbar" style={{ marginTop: 24 }}>
            <Seg label={t("View", "Visning")} value={missingView ? "missing" : "not_in_plex"} onChange={switchView} options={[
              { value: "not_in_plex", label: `${t("On disk, not in Plex", "På disk, ikke i Plex")}${s ? ` (${s.not_in_plex.groups})` : ""}` },
              { value: "missing", label: `${t("In Plex, missing on disk", "I Plex, mangler på disk")}${s ? ` (${s.missing.groups})` : ""}` },
            ]} />
            <input type="search" placeholder={t("Search", "Søk")} value={q} onChange={(e) => setQ(e.target.value)} aria-label={t("Search", "Søk")} />
            {view.startsWith("reason:") && <button className="btn small" onClick={() => switchView("not_in_plex")}>{t("Show all reasons", "Vis alle årsaker")}</button>}
            {selectable.length > 0 && <button className="btn small" onClick={() => setSel([...new Set([...sel, ...selectable])])}>{t(`Select all (${selectable.length})`, `Velg alle (${selectable.length})`)}</button>}
          </div>
          {missingView && <p className="small muted">{t("Plex also removes these itself when the library is scanned and the trash is emptied (Plex → library → ⋯ → Empty Trash).",
            "Plex fjerner også disse selv når biblioteket skannes og papirkurven tømmes (Plex → bibliotek → ⋯ → Empty Trash).")}</p>}
          <div className="table-wrap">
            <table>
              <thead><tr><th style={{ width: 28 }} /><th>{t("Title / folder", "Tittel / mappe")}</th><th>{missingView ? t("Plex library", "Plex-bibliotek") : t("Reason", "Årsak")}</th><th className="r">{t("Files", "Filer")}</th><th className="r">{t("Size", "Størrelse")}</th><th /></tr></thead>
              <tbody>
                {data.items.map((g) => (
                  <Fragment key={g.key}>
                    <tr className="row">
                      <td>{selKey(g) && <input type="checkbox" checked={sel.includes(selKey(g)!)} onChange={() => toggle(selKey(g)!)} aria-label={t(`Select ${g.name}`, `Velg ${g.name}`)} />}</td>
                      <td className="title-cell">
                        <button className="linkish" style={{ fontWeight: 560 }} onClick={() => setOpen(open === g.key ? null : g.key)} aria-expanded={open === g.key}>{g.name}{g.year ? ` (${g.year})` : ""}</button>
                        <small className="path">{g.folder}</small>
                        {g.title_key && <small><button className="linkish" onClick={() => openTitle(g.title_key!)}>{g.title_key.startsWith("dir:") ? t("Show files", "Vis filer") : t("Open title", "Åpne tittel")}</button>{g.title_key.startsWith("dir:") && !g.managed ? t(", not in Radarr/Sonarr", ", ikke i Radarr/Sonarr") : ""}</small>}
                      </td>
                      <td className="small">{missingView ? g.section : <>{g.reason}{g.newest ? <div className="muted">{t("changed", "endret")} {ago(g.newest)}</div> : null}</>}</td>
                      <td className="r">{g.count}</td>
                      <td className="r num">{bytes(g.size)}</td>
                      <td className="r">
                        <div style={{ display: "flex", gap: 6, justifyContent: "flex-end", flexWrap: "wrap" }}>
                          {g.section_key && !missingView && <button className="btn small" onClick={() => rescan(g)}>{t("Ask Plex to scan", "Be Plex skanne")}</button>}
                          {selKey(g) && <button className="btn small" onClick={() => setDialog([selKey(g)!])}>{missingView ? t("Remove from Plex…", "Fjern fra Plex…") : t("Delete from disk…", "Slett fra disk…")}</button>}
                        </div>
                        {!missingView && g.managed && <div className="small muted" style={{ marginTop: 4 }}>{t("Delete through the title (Radarr/Sonarr)", "Slett via tittelen (Radarr/Sonarr)")}</div>}
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
          {data.items.length === 0 && <div className="empty">{t("No differences in this view.", "Ingen avvik i dette utvalget.")}</div>}
        </>
      )}
      {sel.length > 0 && (
        <Tray figure={`${sel.length}`} note={missingView ? t("selected – removed from Plex", "valgt – fjernes fra Plex") : t("selected – deleted from disk", "valgt – slettes fra disk")}>
          <button className="btn" onClick={() => setSel([])}>{t("Clear", "Tøm")}</button>
          <button className="btn danger" onClick={() => setDialog(sel)}>{missingView ? t("Remove from Plex…", "Fjern fra Plex…") : t("Delete from disk…", "Slett fra disk…")}</button>
        </Tray>
      )}
      {dialog && <CleanupDialog mode={missingView ? "plex" : "disk"} keys={dialog} onClose={() => setDialog(null)} onDone={() => { setSel([]); setReload((r) => r + 1); }} />}
    </>
  );
}
