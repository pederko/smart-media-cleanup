import { useEffect, useState } from "react";
import DeleteDialog from "./DeleteDialog";
import { Suggestion } from "../api";
import { ago, bytes, date, fileName, KIND_LABEL } from "../format";
import { Breakdown, RiskPill, useFetch, Poster } from "./common";

type TitleDetail = {
  key: string; kind: string; name: string; year: number | null; library: string; folder: string;
  radarr_id: number | null; sonarr_id: number | null; monitored: number | null; added: number | null;
  tags: string[]; protected: number; protect_reason: string | null; size: number; alloc: number;
  file_count: number; video_count: number; play_count: number; last_played: number | null; users: string[];
  recent_users_count: number; requested_by: string | null; requested_at: number | null; best_resolution: string | null;
  requests: { by: string; plex_username: string | null; at: number | null; watched: boolean }[];
  seasons: Record<string, { plays: number; last: number | null; users: number }>;
  files: { path: string; size: number; nlink: number; mtime: number; is_video: number; is_extra: number; season: number | null; episode: number | null }[];
  suggestions: Suggestion[];
  recent_plays: { date: number; user: string; title: string; parent_index: number | null; percent: number | null }[];
};

export default function TitleDrawer({ id, onClose }: { id: string; onClose: () => void }) {
  const [deleting, setDeleting] = useState<string[] | null>(null);
  const { data, error, reload } = useFetch<TitleDetail>(`/api/titles/${encodeURIComponent(id)}`, [id]);
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);

  const seasonSizes: Record<string, number> = {};
  data?.files.forEach((f) => { if (f.season != null) seasonSizes[f.season] = (seasonSizes[f.season] ?? 0) + f.size; });
  const manager = data?.radarr_id != null ? "Radarr" : data?.sonarr_id != null ? "Sonarr" : null;

  return (
    <>
      <div className="drawer-bg" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-label={data?.name ?? "Tittel"}>
        <button className="btn small close" onClick={onClose}>Lukk</button>
        {error && <div className="notice err">{error}</div>}
        {!data ? <p className="muted">Henter…</p> : (
          <>
            <div className="drawer-head">
              <Poster k={data.key} title={data.name} size="l" />
              <div style={{ minWidth: 0 }}>
                <h1>{data.name}{data.year ? <span className="muted" style={{ fontWeight: 400 }}> ({data.year})</span> : null}</h1>
                <p className="path">{data.folder}</p>
              </div>
            </div>
            {data.protected ? <div className="notice ok">Beskyttet: {data.protect_reason}. Vises aldri som forslag.</div> : null}
            <div className="figures">
              <div className="figure"><div className="v">{bytes(data.alloc)}</div><div className="l">{data.file_count} filer</div></div>
              <div className="figure"><div className="v">{data.play_count}</div><div className="l">avspillinger</div></div>
              <div className="figure"><div className="v">{ago(data.last_played)}</div><div className="l">sist sett</div></div>
              <div className="figure"><div className="v">{data.users.length}</div><div className="l">brukere har sett</div></div>
            </div>
            {(() => {
              const managed = data.radarr_id != null || data.sonarr_id != null;
              const whole = data.suggestions.find((x) => x.kind === "delete_title");
              const seasons = data.suggestions.filter((x) => x.kind === "delete_season");
              if (data.protected || !managed || (!whole && seasons.length === 0)) return null;
              return (
                <div className="delete-row">
                  {whole && <button className="btn danger" onClick={() => setDeleting([whole.id])}>
                    {data.kind === "movie" ? "Slett filmen" : "Slett hele serien"} ({bytes(whole.savings)})…</button>}
                  {seasons.map((x) => (
                    <button key={x.id} className="btn small danger" onClick={() => setDeleting([x.id])}>
                      Slett {x.label.split(" – ").pop()?.toLowerCase()} ({bytes(x.savings)})…</button>
                  ))}
                </div>
              );
            })()}
            <dl className="kv">
              <dt>Bibliotek</dt><dd>{data.library}</dd>
              <dt>Administreres av</dt><dd>{manager ? `${manager}, ${data.monitored ? "overvåket" : "ikke overvåket"}` : "Ingen (bare filsystem/Plex)"}</dd>
              <dt>Lagt til</dt><dd>{date(data.added)}</dd>
              {data.best_resolution && <><dt>Beste oppløsning</dt><dd>{data.best_resolution}</dd></>}
              {data.tags.length > 0 && <><dt>Tagger/etiketter</dt><dd>{data.tags.join(", ")}</dd></>}
              {data.requests.length > 0 && <><dt>Etterspurt av</dt><dd>{data.requests.map((r, i) => (
                <div key={i}>{r.by}, {date(r.at)} <span className={r.watched ? "muted" : "faint"}>{r.watched ? "har sett den" : "har ikke sett den"}</span></div>
              ))}</dd></>}
              {data.users.length > 0 && <><dt>Sett av</dt><dd>{data.users.join(", ")}</dd></>}
            </dl>

            {Object.keys(seasonSizes).length > 1 && (
              <section className="section">
                <h2>Sesonger</h2>
                <table>
                  <thead><tr><th>Sesong</th><th className="r">Størrelse</th><th className="r">Avspillinger</th><th>Sist sett</th></tr></thead>
                  <tbody>
                    {Object.entries(seasonSizes).sort((a, b) => +a[0] - +b[0]).map(([sn, size]) => {
                      const st = data.seasons[sn];
                      return <tr key={sn}><td>{sn}</td><td className="r num">{bytes(size)}</td><td className="r">{st?.plays ?? 0}</td><td className="muted">{ago(st?.last)}</td></tr>;
                    })}
                  </tbody>
                </table>
              </section>
            )}

            <section className="section">
              <h2>Forslag for denne tittelen</h2>
              {data.suggestions.length === 0 ? <p className="muted">Ingen forslag.</p> : data.suggestions.map((s) => (
                <div key={s.id} className="panel" style={{ marginBottom: 12 }}>
                  <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginBottom: 8 }}>
                    <b>{s.action}</b><span className="tag">{KIND_LABEL[s.kind] ?? s.kind}</span><RiskPill risk={s.risk} />
                    <span className="muted" style={{ marginLeft: "auto" }}>frigjør {bytes(s.savings)}</span>
                  </div>
                  <Breakdown components={s.components} score={s.score} />
                </div>
              ))}
            </section>

            {data.recent_plays.length > 0 && (
              <section className="section">
                <h2>Siste avspillinger</h2>
                <table>
                  <tbody>
                    {data.recent_plays.slice(0, 15).map((p, i) => (
                      <tr key={i}><td className="muted small num">{date(p.date)}</td><td>{p.user}</td><td className="muted small">{p.parent_index != null ? `Sesong ${p.parent_index}` : ""}</td><td className="r muted small">{p.percent != null ? `${p.percent} %` : ""}</td></tr>
                    ))}
                  </tbody>
                </table>
              </section>
            )}

            <section className="section">
              <h2>Filer</h2>
              <table>
                <tbody>
                  {data.files.slice(0, 200).map((f) => (
                    <tr key={f.path}>
                      <td><span title={f.path}>{fileName(f.path)}</span>{f.is_extra ? <span className="tag" style={{ marginLeft: 8 }}>ekstra</span> : null}{f.nlink > 1 ? <span className="tag" style={{ marginLeft: 8 }}>{f.nlink} hardlenker</span> : null}</td>
                      <td className="r num">{bytes(f.size)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {data.files.length > 200 && <p className="small muted">Viser 200 av {data.files.length} filer.</p>}
            </section>
          </>
        )}
      </aside>
      {deleting && <DeleteDialog ids={deleting} onClose={() => setDeleting(null)} onDone={() => reload()} />}
    </>
  );
}
