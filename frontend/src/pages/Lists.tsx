import { useEffect, useState } from "react";
import { qs } from "../api";
import { ago, bytes, date, fileName, num } from "../format";
import { ErrorNote, RequestedBy, useFetch, useOpenTitle, useRefreshTick } from "../components/common";

type Title = { key: string; kind: string; name: string; year: number | null; library: string; alloc: number; file_count: number;
  play_count: number; last_played: number | null; users_count: number; protected: number; protect_reason: string | null;
  monitored: number | null; radarr_id: number | null; sonarr_id: number | null; best_resolution: string | null; added: number | null;
  requests: { by: string; at: number | null; watched: boolean }[] };

function useDebounced(v: string) {
  const [d, setD] = useState(v);
  useEffect(() => { const t = setTimeout(() => setD(v), 250); return () => clearTimeout(t); }, [v]);
  return d;
}

export function TitlesPage() {
  const tick = useRefreshTick();
  const openTitle = useOpenTitle();
  const [q, setQ] = useState("");
  const [kind, setKind] = useState("");
  const [prot, setProt] = useState("");
  const [sort, setSort] = useState("alloc");
  const [order, setOrder] = useState("desc");
  const [limit, setLimit] = useState(100);
  const dq = useDebounced(q);
  const { data, error } = useFetch<{ total: number; items: Title[] }>(`/api/titles${qs({ q: dq, kind, protected: prot, sort, order, limit })}`, [tick]);
  const sortBy = (c: string) => { if (sort === c) setOrder(order === "desc" ? "asc" : "desc"); else { setSort(c); setOrder(c === "name" ? "asc" : "desc"); } };
  const th = (c: string, l: string, r = false) => (
    <th className={r ? "r" : undefined}><button onClick={() => sortBy(c)} aria-sort={sort === c ? (order === "asc" ? "ascending" : "descending") : undefined}>{l}{sort === c ? (order === "asc" ? " ↑" : " ↓") : ""}</button></th>
  );
  return (
    <>
      <h1>Titler</h1>
      <p className="lede">Alle filmer og serier slik appen har koblet dem sammen fra filsystemet, Radarr, Sonarr, Plex og Tautulli.</p>
      <div className="toolbar">
        <input type="search" placeholder="Søk etter tittel" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Søk" />
        <div className="seg" role="group" aria-label="Type">
          {[["", "Alle"], ["movie", "Filmer"], ["series", "Serier"]].map(([v, l]) => <button key={v} aria-pressed={kind === v} onClick={() => setKind(v)}>{l}</button>)}
        </div>
        <div className="seg" role="group" aria-label="Beskyttelse">
          {[["", "Alle"], ["1", "Beskyttet"], ["0", "Ikke beskyttet"]].map(([v, l]) => <button key={v} aria-pressed={prot === v} onClick={() => setProt(v)}>{l}</button>)}
        </div>
      </div>
      <ErrorNote error={error} />
      {data && <p className="small muted">{num(data.total)} titler</p>}
      <div className="table-wrap">
        <table>
          <thead><tr>{th("name", "Tittel")}<th>Bibliotek</th>{th("plays", "Avspillinger", true)}{th("last_played", "Sist sett")}{th("added", "Lagt til")}{th("alloc", "Størrelse", true)}</tr></thead>
          <tbody>
            {data?.items.map((t) => (
              <tr key={t.key} className="row">
                <td className="title-cell">
                  <button className="btn small" style={{ border: 0, background: "none", padding: 0, fontWeight: 560, textAlign: "left" }} onClick={() => openTitle(t.key)}>{t.name}{t.year ? ` (${t.year})` : ""}</button>
                  <small>{t.kind === "movie" ? "Film" : "Serie"}{t.best_resolution ? `, ${t.best_resolution}` : ""}{t.radarr_id != null ? ", Radarr" : t.sonarr_id != null ? ", Sonarr" : ""}{t.protected ? `, beskyttet` : ""}</small>
                  {t.requests?.length ? <small><RequestedBy requests={t.requests} /></small> : null}
                </td>
                <td>{t.library}</td>
                <td className="r">{t.play_count}{t.users_count ? <span className="faint small"> / {t.users_count} br.</span> : null}</td>
                <td className="muted">{ago(t.last_played)}</td>
                <td className="muted small">{date(t.added)}</td>
                <td className="r num">{bytes(t.alloc)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data && data.total > data.items.length && <p><button className="btn" onClick={() => setLimit(limit + 200)}>Vis flere</button></p>}
    </>
  );
}

type Dup = { id: string; kind: string; title_key: string | null; label: string; total: number; reclaimable: number; keep_reason: string | null;
  files: { path: string; size: number; resolution: string | null; managed: boolean; keep: boolean; nlink: number }[] };

const DUP_KIND: Record<string, [string, string]> = {
  identical: ["Identiske kopier", "Samme størrelse og samme innhold (delvis hash av start, midt og slutt), men separate filer på disk. Én kan fjernes uten å miste noe."],
  versions: ["Flere versjoner", "Samme film eller episode i ulike utgaver eller oppløsninger. Innholdet er ikke identisk, så du må velge hvilken du vil beholde."],
  hardlink: ["Hardlenker", "Samme fil på disk under flere navn. Dette er ikke duplikater og tar ikke ekstra plass."],
};

export function DuplicatesPage() {
  const tick = useRefreshTick();
  const openTitle = useOpenTitle();
  const [kind, setKind] = useState("identical");
  const { data, error } = useFetch<{ items: Dup[] }>(`/api/duplicates${qs({ kind })}`, [tick]);
  const total = data?.items.reduce((s, d) => s + d.reclaimable, 0) ?? 0;
  return (
    <>
      <h1>Duplikater og versjoner</h1>
      <p className="lede">Lik tittel alene regnes aldri som duplikat. Tre ulike tilfeller holdes adskilt.</p>
      <div className="toolbar">
        <div className="seg" role="group" aria-label="Type">
          {Object.entries(DUP_KIND).map(([k, [l]]) => <button key={k} aria-pressed={kind === k} onClick={() => setKind(k)}>{l}</button>)}
        </div>
      </div>
      <p className="muted">{DUP_KIND[kind][1]}</p>
      <ErrorNote error={error} />
      {data && kind !== "hardlink" && <p className="small muted">{data.items.length} {data.items.length === 1 ? "gruppe" : "grupper"}, opptil {bytes(total)} kan frigjøres.</p>}
      {data?.items.length === 0 && <div className="empty">Ingen funnet.</div>}
      <div className="grid" style={{ gap: 14 }}>
        {data?.items.map((d) => (
          <section key={d.id} className="panel">
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
              <h3>{d.title_key ? <button className="btn small" style={{ border: 0, background: "none", padding: 0, fontWeight: 600, fontSize: 15 }} onClick={() => openTitle(d.title_key!)}>{d.label.split(": ").slice(1).join(": ") || d.label}</button> : d.label}</h3>
              {d.kind !== "hardlink" && <span className="num">{bytes(d.reclaimable)} kan frigjøres</span>}
            </div>
            <table>
              <tbody>
                {d.files.map((f) => (
                  <tr key={f.path}>
                    <td>{fileName(f.path)}<div className="path">{f.path.split("/").slice(0, -1).join("/")}</div></td>
                    <td className="small">{f.resolution ?? ""}</td>
                    <td className="small">{f.managed ? "Radarr/Sonarr" : ""}</td>
                    <td className="small">{d.kind === "hardlink" ? "" : f.keep ? <b>Beholdes</b> : <span className="muted">Kan fjernes</span>}</td>
                    <td className="r num">{bytes(f.size)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {d.keep_reason && d.kind !== "hardlink" && <p className="small muted" style={{ marginBottom: 0 }}>Foreslått beholdt fordi den {d.keep_reason}.</p>}
          </section>
        ))}
      </div>
    </>
  );
}

type F = { path: string; size: number; library: string; ext: string; nlink: number; mtime: number; is_extra: number;
  title_key: string | null; title_name: string | null; play_count: number | null; last_played: number | null };

export function FilesPage() {
  const tick = useRefreshTick();
  const openTitle = useOpenTitle();
  const [library, setLibrary] = useState("");
  const [ext, setExt] = useState("");
  const [minGb, setMinGb] = useState("20");
  const [limit, setLimit] = useState(100);
  const { data, error } = useFetch<{ total: number; total_bytes: number; items: F[] }>(`/api/files/largest${qs({ library, ext, min_gb: minGb, limit })}`, [tick]);
  const settings = useFetch<{ libraries: { name: string }[] }>("/api/settings");
  return (
    <>
      <h1>Største filer</h1>
      <p className="lede">Enkeltfiler sortert etter størrelse. Nyttig for å finne 4K-remuxer, ISO-filer og uvanlig store episoder.</p>
      <div className="toolbar">
        <select value={library} onChange={(e) => setLibrary(e.target.value)} aria-label="Bibliotek">
          <option value="">Alle bibliotek</option>
          {settings.data?.libraries.map((l) => <option key={l.name}>{l.name}</option>)}
        </select>
        <select value={ext} onChange={(e) => setExt(e.target.value)} aria-label="Filtype">
          <option value="">Alle filtyper</option>
          {[".mkv", ".mp4", ".iso", ".m2ts", ".ts", ".avi"].map((x) => <option key={x}>{x}</option>)}
        </select>
        <label className="check small">Minst <input type="number" min={0} value={minGb} onChange={(e) => setMinGb(e.target.value)} /> GB</label>
      </div>
      <ErrorNote error={error} />
      {data && <p className="small muted">{num(data.total)} filer, {bytes(data.total_bytes)} til sammen.</p>}
      <div className="table-wrap">
        <table>
          <thead><tr><th>Fil</th><th>Tittel</th><th>Sist sett</th><th className="r">Størrelse</th></tr></thead>
          <tbody>
            {data?.items.map((f) => (
              <tr key={f.path} className="row">
                <td>{fileName(f.path)}{f.nlink > 1 && <span className="tag" style={{ marginLeft: 8 }}>{f.nlink} hardlenker</span>}{f.ext === ".iso" && <span className="tag" style={{ marginLeft: 8 }}>ISO</span>}<div className="path">{f.library}</div></td>
                <td>{f.title_key ? <button className="btn small" style={{ border: 0, background: "none", padding: 0, textAlign: "left" }} onClick={() => openTitle(f.title_key!)}>{f.title_name}</button> : <span className="muted">–</span>}</td>
                <td className="muted">{f.title_key ? ago(f.last_played) : ""}</td>
                <td className="r num">{bytes(f.size)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data && data.total > data.items.length && <p><button className="btn" onClick={() => setLimit(limit + 200)}>Vis flere</button></p>}
    </>
  );
}
