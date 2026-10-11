import { useMemo, useState } from "react";
import { ago, bytes, num } from "../format";
import { plural, t } from "../i18n";
import { Empty, ErrorNote, Loading, PageHeader, Seg, Tray, useFetch, useOpenTitle, useRefreshTick } from "../components/common";
import { Change, ReviewDialog } from "../components/ArrChanges";
import SeedingLimits, { QbitLimits } from "../components/SeedingLimits";

type Torrent = { hash: string; name: string; category: string; arr: string | null; state: string; class: string; stopped: boolean;
  complete: boolean; ratio: number; seeding_minutes: number; size: number; added: number | null; last_activity: number | null;
  limit: "global" | "none" | "own"; import_status: string | null; title_name: string | null; title_key: string | null; freed: number;
  removable: boolean; files_removable: boolean };
type Resp = QbitLimits & { version?: string; torrents?: Torrent[]; arr_checked?: boolean; actions_enabled?: boolean; files_enabled?: boolean;
  summary?: { count: number; size: number; seeding: number; by_class: Record<string, { count: number; size: number; freed: number }> } };

const CLASSES = ["imported", "orphaned", "error", "importing", "downloading", "other", "unknown"] as const;
const classLabel = (c: string) => ({
  imported: t("In library", "I biblioteket"), orphaned: t("Orphaned", "Foreldreløs"), error: t("Error", "Feil"),
  importing: t("Being imported", "Importeres"), downloading: t("Downloading", "Lastes ned"), other: t("Not from Radarr/Sonarr", "Ikke fra Radarr/Sonarr"),
  unknown: t("Unknown", "Ukjent"),
} as Record<string, string>)[c] ?? c;
const classHelp = (c: string) => ({
  imported: t("Finished, and the content is in a library (hardlink or copy). Safe to remove with its files – the library copy stays.",
    "Ferdig, og innholdet ligger i et bibliotek (hardlenke eller kopi). Trygt å fjerne med filene – kopien i biblioteket blir."),
  orphaned: t("From Radarr/Sonarr, finished, not in their queue, and the content is in the downloads folder but not in any library – never imported, or the title was deleted since.",
    "Fra Radarr/Sonarr, ferdig, ikke i køen deres, og innholdet ligger i nedlastingsmappen men ikke i noe bibliotek – aldri importert, eller tittelen er slettet siden."),
  error: t("qBittorrent reports an error or missing files.", "qBittorrent melder feil eller manglende filer."),
  importing: t("Radarr/Sonarr still has it in the queue – left alone.", "Radarr/Sonarr har den fortsatt i køen – røres ikke."),
  downloading: t("Not finished.", "Ikke ferdig."),
  other: t("Another category than Radarr/Sonarr use.", "En annen kategori enn Radarr/Sonarr bruker."),
  unknown: t("From Radarr/Sonarr, but its files are not in a scanned downloads library, so the app cannot check them.",
    "Fra Radarr/Sonarr, men filene ligger ikke i et skannet nedlastingsbibliotek, så appen kan ikke sjekke dem."),
} as Record<string, string>)[c] ?? "";

export default function TorrentsPage() {
  const tick = useRefreshTick();
  const openTitle = useOpenTitle();
  const [reload, setReload] = useState(0);
  const { data, error, loading } = useFetch<Resp>("/api/torrents", [tick, reload]);
  const [view, setView] = useState<string>("imported");
  const [q, setQ] = useState("");
  const [sel, setSel] = useState<string[]>([]);
  const [basket, setBasket] = useState<Record<string, Change>>({});
  const [review, setReview] = useState<Change[] | null>(null);
  const toggle = (id: string, ch: Change | null) => setBasket((b) => { const n = { ...b }; if (ch) n[id] = ch; else delete n[id]; return n; });

  const all = data?.torrents ?? [];
  const list = useMemo(() => all.filter((x) => (view === "all" || (view === "seeding" ? x.complete && !x.stopped && x.class !== "error" : x.class === view))
    && (!q || x.name.toLowerCase().includes(q.toLowerCase()) || (x.title_name ?? "").toLowerCase().includes(q.toLowerCase()))), [all, view, q]);
  const chosen = all.filter((x) => sel.includes(x.hash));
  const s = data?.summary;
  const by = s?.by_class ?? {};
  const toggleSel = (h: string) => setSel(sel.includes(h) ? sel.filter((x) => x !== h) : [...sel, h]);
  const act = (change: Change) => setReview([change]);
  const hashes = (f: (x: Torrent) => boolean) => chosen.filter(f).map((x) => x.hash);
  const limitLabel = (x: Torrent) => ({ global: t("global", "global"), none: t("no limit", "ingen grense"), own: t("own", "egen") })[x.limit];

  return (
    <>
      <PageHeader title={t("Torrents", "Torrenter")}
        lede={t("Everything in qBittorrent: what is already in your library, what is orphaned or broken, and how long things seed. Nothing is removed or changed until you confirm.",
          "Alt i qBittorrent: hva som allerede ligger i biblioteket, hva som er foreldreløst eller ødelagt, og hvor lenge ting deles. Ingenting fjernes eller endres før du bekrefter.")} />
      <ErrorNote error={error} />
      {!data && loading && <Loading />}
      {data && !data.configured && (
        <Empty>{t("qBittorrent is not connected.", "qBittorrent er ikke koblet til.")} <a href="#/settings/services">{t("Settings → Connections", "Innstillinger → Tilkoblinger")}</a></Empty>
      )}
      {data?.error && <ErrorNote error={data.error} />}
      {data?.configured && !data.error && s && (
        <>
          <section className="brief">
            <p className="brief-lead">
              <b>{plural(s.count, ["torrent", "torrents"], ["torrent", "torrenter"])}</b> {t("use", "bruker")} <b>{bytes(s.size)}</b>, {t(`${s.seeding} are seeding.`, `${s.seeding} deler.`)}{" "}
              {by.imported ? <>{t(`${by.imported.count} are already in your library – removing them frees`, `${by.imported.count} ligger allerede i biblioteket – fjernes de, frigjøres`)} <b>{bytes(by.imported.freed)}</b>.</> : null}
            </p>
            <ul className="brief-points">
              {by.orphaned && <li>{t(`${by.orphaned.count} orphaned (${bytes(by.orphaned.size)}) – finished, from Radarr/Sonarr, but not in any library.`, `${by.orphaned.count} foreldreløse (${bytes(by.orphaned.size)}) – ferdige, fra Radarr/Sonarr, men ikke i noe bibliotek.`)}</li>}
              {by.error && <li>{t(`${by.error.count} with errors or missing files.`, `${by.error.count} med feil eller manglende filer.`)}</li>}
              {!data.arr_checked && <li className="warn-text">{t("Radarr or Sonarr did not answer, so nothing from them is called orphaned right now.", "Radarr eller Sonarr svarte ikke, så ingenting fra dem kalles foreldreløst nå.")}</li>}
            </ul>
            <p className="small muted">qBittorrent {data.version}. {t("Hardlinked downloads free nothing when removed, but they stop seeding.", "Hardlenkede nedlastinger frigjør ingenting når de fjernes, men slutter å dele.")}</p>
          </section>

          <details className="panel" style={{ margin: "8px 0 24px" }} open={!data.rule?.enabled}>
            <summary><b>{t("Seeding limits", "Delingsgrenser")}</b> <span className="small muted">· {data.rule?.enabled ? t("the rule for Radarr/Sonarr is on", "regelen for Radarr/Sonarr er på") : t("the rule for Radarr/Sonarr is off", "regelen for Radarr/Sonarr er av")}</span></summary>
            <div style={{ marginTop: 12 }}>
              <SeedingLimits q={data} changes={basket} toggle={toggle} />
              {Object.keys(basket).length > 0 && (
                <div className="toolbar" style={{ marginTop: 10 }}>
                  <button className="btn primary" onClick={() => setReview(Object.values(basket))}>{t("Review…", "Se over…")}</button>
                  <button className="btn small" onClick={() => setBasket({})}>{t("Clear", "Tøm")}</button>
                </div>
              )}
            </div>
          </details>

          <div className="toolbar">
            <Seg label={t("Show", "Vis")} value={view} onChange={(v) => { setView(v); setSel([]); }} options={[
              ...CLASSES.filter((c) => by[c]).map((c) => ({ value: c, label: <>{classLabel(c)} <span className="muted">{by[c].count}</span></> })),
              { value: "seeding", label: t("Seeding", "Deler") }, { value: "all", label: t("All", "Alle") },
            ]} />
            <input type="search" placeholder={t("Search", "Søk")} value={q} onChange={(e) => setQ(e.target.value)} aria-label={t("Search", "Søk")} />
          </div>
          {view !== "all" && view !== "seeding" && <p className="small muted">{classHelp(view)}</p>}
          <div className="toolbar">
            <button className="btn small" onClick={() => setSel(list.filter((x) => x.removable).map((x) => x.hash))}>{t(`Select all that can be removed (${list.filter((x) => x.removable).length})`, `Velg alle som kan fjernes (${list.filter((x) => x.removable).length})`)}</button>
            {sel.length > 0 && <button className="btn small" onClick={() => setSel([])}>{t("Clear selection", "Fjern utvalg")}</button>}
          </div>

          {list.length === 0 ? <Empty>{t("Nothing here.", "Ingenting her.")}</Empty> : (
            <div className="table-wrap">
              <table>
                <thead><tr><th style={{ width: 28 }} /><th>{t("Torrent", "Torrent")}</th><th>{t("Status", "Status")}</th><th className="r">{t("Size", "Størrelse")}</th>
                  <th className="r">Ratio</th><th className="r">{t("Seeded", "Delt")}</th><th>{t("Limit", "Grense")}</th><th className="r">{t("Frees", "Frigjør")}</th></tr></thead>
                <tbody>
                  {list.map((x) => (
                    <tr key={x.hash}>
                      <td><input type="checkbox" checked={sel.includes(x.hash)} onChange={() => toggleSel(x.hash)} aria-label={x.name} /></td>
                      <td className="title-cell">
                        <span style={{ fontWeight: 560, wordBreak: "break-word" }}>{x.name}</span>
                        <small>{[x.category || t("no category", "ingen kategori"), x.state, x.added ? t(`added ${ago(x.added)}`, `lagt til ${ago(x.added)}`) : null].filter(Boolean).join(" · ")}</small>
                        {x.title_name && <small>{t("In library as", "I biblioteket som")} {x.title_key ? <button className="linkish" onClick={() => openTitle(x.title_key!)}>{x.title_name}</button> : x.title_name}</small>}
                      </td>
                      <td className="small"><span className={x.class === "imported" ? "ok-text" : x.class === "orphaned" || x.class === "error" ? "warn-text" : "muted"} title={classHelp(x.class)}>{classLabel(x.class)}</span>
                        {x.import_status === "hardlinked" && <div className="muted">{t("hardlink", "hardlenke")}</div>}</td>
                      <td className="r">{bytes(x.size)}</td>
                      <td className="r">{num(x.ratio, 2)}</td>
                      <td className="r small">{num(x.seeding_minutes / 60 / 24, 1)} {t("d", "d")}</td>
                      <td className="small">{limitLabel(x)}</td>
                      <td className="r">{x.freed ? bytes(x.freed) : "–"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {sel.length > 0 && <div style={{ height: 110 }} aria-hidden />}
        </>
      )}

      {sel.length > 0 && (
        <Tray figure={plural(sel.length, ["torrent", "torrents"], ["torrent", "torrenter"])}
          note={chosen.some((x) => x.files_removable) ? t(`Up to ${bytes(chosen.filter((x) => x.files_removable).reduce((a, x) => a + x.freed, 0))} freed with files`, `Opptil ${bytes(chosen.filter((x) => x.files_removable).reduce((a, x) => a + x.freed, 0))} frigjøres med filer`) : t("Nothing confirmed yet", "Ingenting bekreftet ennå")}>
          <button className="btn small" onClick={() => act({ op: "qbit_stop", hashes: sel })}>{t("Stop", "Stopp")}</button>
          <button className="btn small" onClick={() => act({ op: "qbit_limits", hashes: sel, mode: "global" })}>{t("Use the global limit", "Bruk global grense")}</button>
          <button className="btn small" disabled={!hashes((x) => x.removable).length} onClick={() => act({ op: "qbit_remove", hashes: hashes((x) => x.removable), files: false })}>{t("Remove torrent", "Fjern torrent")}</button>
          <button className="btn primary" disabled={!hashes((x) => x.files_removable).length} onClick={() => act({ op: "qbit_remove", hashes: hashes((x) => x.files_removable), files: true })}>{t("Remove with files…", "Fjern med filer…")}</button>
        </Tray>
      )}
      {review && <ReviewDialog changes={review} enabled={!!data?.actions_enabled} onClose={() => setReview(null)}
        onDone={() => { setSel([]); setBasket({}); setReload((r) => r + 1); }} />}
    </>
  );
}
