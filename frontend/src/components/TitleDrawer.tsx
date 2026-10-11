import { useState } from "react";
import DeleteDialog from "./DeleteDialog";
import CleanupDialog from "./CleanupDialog";
import ReleaseSearch from "./ReleaseSearch";
import SwapList from "./Swaps";
import { Suggestion } from "../api";
import { ago, bytes, date, fileName, kindLabel } from "../format";
import { plural, t } from "../i18n";
import { Breakdown, Drawer, Loading, Poster, RiskPill, useFetch } from "./common";

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

/** Everything about one title: facts, delete buttons, smaller versions, suggestions, history and files. */
export default function TitleDrawer({ id, onClose }: { id: string; onClose: () => void }) {
  const [deleting, setDeleting] = useState<string[] | null>(null);
  const [diskDelete, setDiskDelete] = useState(false);
  const { data, error, reload } = useFetch<TitleDetail>(`/api/titles/${encodeURIComponent(id)}`, [id]);

  const seasonSizes: Record<string, number> = {};
  data?.files.forEach((f) => { if (f.season != null) seasonSizes[f.season] = (seasonSizes[f.season] ?? 0) + f.size; });
  const manager = data?.radarr_id != null ? "Radarr" : data?.sonarr_id != null ? "Sonarr" : null;

  return (
    <>
      <Drawer label={data?.name ?? t("Title", "Tittel")} onClose={onClose}>
        {error && <div className="notice err">{error}</div>}
        {!data ? <Loading /> : (
          <>
            <div className="drawer-head">
              <Poster k={data.key} title={data.name} size="l" />
              <div style={{ minWidth: 0 }}>
                <h1>{data.name}{data.year ? <span className="muted" style={{ fontWeight: 400 }}> ({data.year})</span> : null}</h1>
                <p className="path">{data.folder}</p>
              </div>
            </div>
            {data.protected ? <div className="notice ok">{t("Protected:", "Beskyttet:")} {data.protect_reason}. {t("Never suggested.", "Vises aldri som forslag.")}</div> : null}
            <div className="figures">
              <div className="figure"><div className="v">{bytes(data.alloc)}</div><div className="l">{plural(data.file_count, ["file", "files"], ["fil", "filer"])}</div></div>
              <div className="figure"><div className="v">{data.play_count}</div><div className="l">{t("plays", "avspillinger")}</div></div>
              <div className="figure"><div className="v">{ago(data.last_played)}</div><div className="l">{t("last watched", "sist sett")}</div></div>
              <div className="figure"><div className="v">{data.users.length}</div><div className="l">{t("users have watched", "brukere har sett")}</div></div>
            </div>
            {(() => {
              const managed = data.radarr_id != null || data.sonarr_id != null;
              const whole = data.suggestions.find((x) => x.kind === "delete_title");
              const seasons = data.suggestions.filter((x) => x.kind === "delete_season");
              if (!data.protected && !managed && data.key.startsWith("dir:")) {
                return (
                  <div className="delete-row">
                    <button className="btn danger" onClick={() => setDiskDelete(true)}>{t(`Delete the folder from disk (${bytes(data.alloc || data.size)})…`, `Slett mappen fra disk (${bytes(data.alloc || data.size)})…`)}</button>
                    <span className="small muted">{t("Neither in Radarr nor Sonarr, so it is deleted directly on disk.", "Ligger verken i Radarr eller Sonarr, så den slettes direkte på disk.")}</span>
                  </div>
                );
              }
              if (data.protected || !managed || (!whole && seasons.length === 0)) return null;
              return (
                <div className="delete-row">
                  {whole && <button className="btn danger" onClick={() => setDeleting([whole.id])}>{whole.label} ({bytes(whole.savings)})…</button>}
                  {seasons.map((x) => <button key={x.id} className="btn small danger" onClick={() => setDeleting([x.id])}>{x.label} ({bytes(x.savings)})…</button>)}
                </div>
              );
            })()}
            <dl className="kv">
              <dt>{t("Library", "Bibliotek")}</dt><dd>{data.library}</dd>
              <dt>{t("Managed by", "Administreres av")}</dt><dd>{manager ? `${manager}, ${data.monitored ? t("monitored", "overvåket") : t("not monitored", "ikke overvåket")}` : t("Nothing (disk/Plex only)", "Ingen (bare disk/Plex)")}</dd>
              <dt>{t("Added", "Lagt til")}</dt><dd>{date(data.added)}</dd>
              {data.best_resolution && <><dt>{t("Best resolution", "Beste oppløsning")}</dt><dd>{data.best_resolution}</dd></>}
              {data.tags.length > 0 && <><dt>{t("Tags/labels", "Tagger/etiketter")}</dt><dd>{data.tags.join(", ")}</dd></>}
              {data.requests.length > 0 && <><dt>{t("Requested by", "Etterspurt av")}</dt><dd>{data.requests.map((r, i) => (
                <div key={i}>{r.by}, {date(r.at)} <span className={r.watched ? "muted" : "faint"}>{r.watched ? t("has watched it", "har sett den") : t("has not watched it", "har ikke sett den")}</span></div>
              ))}</dd></>}
              {data.users.length > 0 && <><dt>{t("Watched by", "Sett av")}</dt><dd>{data.users.join(", ")}</dd></>}
            </dl>

            {Object.keys(seasonSizes).length > 1 && (
              <section className="section">
                <h2>{t("Seasons", "Sesonger")}</h2>
                <table>
                  <thead><tr><th>{t("Season", "Sesong")}</th><th className="r">{t("Size", "Størrelse")}</th><th className="r">{t("Plays", "Avspillinger")}</th><th>{t("Last watched", "Sist sett")}</th></tr></thead>
                  <tbody>
                    {Object.entries(seasonSizes).sort((a, b) => +a[0] - +b[0]).map(([sn, size]) => {
                      const st = data.seasons[sn];
                      return <tr key={sn}><td>{sn}</td><td className="r num">{bytes(size)}</td><td className="r">{st?.plays ?? 0}</td><td className="muted">{ago(st?.last)}</td></tr>;
                    })}
                  </tbody>
                </table>
              </section>
            )}

            {(data.radarr_id != null || data.sonarr_id != null) && (
              <section className="section">
                <h2>{t("Smaller versions", "Mindre versjoner")}</h2>
                <p className="small muted" style={{ marginTop: -6 }}>{t(`Searches your indexers through ${manager} for smaller editions${data.sonarr_id != null ? " of a season" : ""}, and recommends which to choose.`,
                  `Søker i indekserne dine via ${manager} etter mindre utgaver${data.sonarr_id != null ? " av en sesong" : ""}, og anbefaler hvilke som bør velges.`)}</p>
                <div className="release-list">
                  {data.radarr_id != null
                    ? <ReleaseSearch titleKey={data.key} />
                    : Object.keys(seasonSizes).sort((a, b) => +a - +b).map((sn) => (
                        <ReleaseSearch key={sn} titleKey={data.key} season={+sn} label={t(`Season ${sn} (${bytes(seasonSizes[sn])})`, `Sesong ${sn} (${bytes(seasonSizes[sn])})`)} />
                      ))}
                </div>
                <SwapList titleKey={data.key} />
              </section>
            )}

            <section className="section">
              <h2>{t("Suggestions for this title", "Forslag for denne tittelen")}</h2>
              {data.suggestions.length === 0 ? <p className="muted">{t("No suggestions.", "Ingen forslag.")}</p> : data.suggestions.map((s) => (
                <div key={s.id} className="panel" style={{ marginBottom: 12 }}>
                  <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginBottom: 8 }}>
                    <b>{s.label}</b><span className="tag">{kindLabel(s.kind)}</span><RiskPill risk={s.risk} />
                    <span className="muted" style={{ marginLeft: "auto" }}>{t("frees", "frigjør")} {bytes(s.savings)}</span>
                  </div>
                  <Breakdown components={s.components} score={s.score} />
                </div>
              ))}
            </section>

            {data.recent_plays.length > 0 && (
              <section className="section">
                <h2>{t("Recent plays", "Siste avspillinger")}</h2>
                <table><tbody>
                  {data.recent_plays.slice(0, 15).map((p, i) => (
                    <tr key={i}><td className="muted small num">{date(p.date)}</td><td>{p.user}</td><td className="muted small">{p.parent_index != null ? t(`Season ${p.parent_index}`, `Sesong ${p.parent_index}`) : ""}</td><td className="r muted small">{p.percent != null ? `${p.percent} %` : ""}</td></tr>
                  ))}
                </tbody></table>
              </section>
            )}

            <section className="section">
              <h2>{t("Files", "Filer")}</h2>
              <table><tbody>
                {data.files.slice(0, 200).map((f) => (
                  <tr key={f.path}>
                    <td><span title={f.path}>{fileName(f.path)}</span>{f.is_extra ? <span className="tag" style={{ marginLeft: 8 }}>{t("extra", "ekstra")}</span> : null}{f.nlink > 1 ? <span className="tag" style={{ marginLeft: 8 }}>{t(`${f.nlink} hardlinks`, `${f.nlink} hardlenker`)}</span> : null}</td>
                    <td className="r num">{bytes(f.size)}</td>
                  </tr>
                ))}
              </tbody></table>
              {data.files.length > 200 && <p className="small muted">{t(`Showing 200 of ${data.files.length} files.`, `Viser 200 av ${data.files.length} filer.`)}</p>}
            </section>
          </>
        )}
      </Drawer>
      {diskDelete && data && <CleanupDialog mode="disk" keys={[data.key]} onClose={() => setDiskDelete(false)} onDone={() => reload()} />}
      {deleting && <DeleteDialog ids={deleting} onClose={() => setDeleting(null)} onDone={() => reload()} />}
    </>
  );
}
