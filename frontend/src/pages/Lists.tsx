import { Fragment, useEffect, useState } from "react";
import ReleaseSearch from "../components/ReleaseSearch";
import { qs } from "../api";
import { ago, bytes, date, fileName, num } from "../format";
import { ErrorNote, Poster, RequestedBy, useFetch, useOpenTitle, useRefreshTick } from "../components/common";

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
                  <div className="with-poster">
                    <Poster k={t.key} title={t.name} size="m" />
                    <div style={{ minWidth: 0 }}>
                      <button className="btn small" style={{ border: 0, background: "none", padding: 0, fontWeight: 560, textAlign: "left" }} onClick={() => openTitle(t.key)}>{t.name}{t.year ? ` (${t.year})` : ""}</button>
                      <small>{t.kind === "movie" ? "Film" : "Serie"}{t.best_resolution ? `, ${t.best_resolution}` : ""}{t.radarr_id != null ? ", Radarr" : t.sonarr_id != null ? ", Sonarr" : ""}{t.protected ? `, beskyttet` : ""}</small>
                      {t.requests?.length ? <small><RequestedBy requests={t.requests} /></small> : null}
                    </div>
                  </div>
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

type F = { year?: number | null; radarr_id?: number | null; sonarr_id?: number | null; season?: number | null; path: string; size: number; library: string; ext: string; nlink: number; mtime: number; is_extra: number;
  title_key: string | null; title_name: string | null; play_count: number | null; last_played: number | null };

export function FilesPage() {
  const tick = useRefreshTick();
  const openTitle = useOpenTitle();
  const [library, setLibrary] = useState("");
  const [ext, setExt] = useState("");
  const [minGb, setMinGb] = useState("20");
  const [limit, setLimit] = useState(100);
  const [search, setSearch] = useState<string | null>(null);
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
          <thead><tr><th>Fil</th><th>Tittel</th><th>Sist sett</th><th className="r">Størrelse</th><th /></tr></thead>
          <tbody>
            {data?.items.map((f) => (
              <Fragment key={f.path}>
              <tr className="row">
                <td>{fileName(f.path)}{f.nlink > 1 && <span className="tag" style={{ marginLeft: 8 }}>{f.nlink} hardlenker</span>}{f.ext === ".iso" && <span className="tag" style={{ marginLeft: 8 }}>ISO</span>}<div className="path">{f.library}</div></td>
                <td>{f.title_key ? <button className="linkish" style={{ textAlign: "left" }} onClick={() => openTitle(f.title_key!)}>{f.title_name}{f.year ? ` (${f.year})` : ""}</button> : <span className="muted">–</span>}
                  {f.season != null && <div className="small muted">Sesong {f.season}</div>}</td>
                <td className="muted">{f.title_key ? ago(f.last_played) : ""}</td>
                <td className="r num">{bytes(f.size)}</td>
                <td className="r">{f.title_key && (f.radarr_id != null || (f.sonarr_id != null && f.season != null)) &&
                  <button className="btn small" onClick={() => setSearch(search === f.path ? null : f.path)} aria-expanded={search === f.path}>{search === f.path ? "Skjul" : "Finn mindre"}</button>}</td>
              </tr>
              {search === f.path && f.title_key && (
                <tr className="detail"><td colSpan={5}>
                  <ReleaseSearch titleKey={f.title_key} season={f.radarr_id != null ? undefined : f.season ?? undefined} autoStart />
                </td></tr>
              )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
      {data && data.total > data.items.length && <p><button className="btn" onClick={() => setLimit(limit + 200)}>Vis flere</button></p>}
    </>
  );
}
