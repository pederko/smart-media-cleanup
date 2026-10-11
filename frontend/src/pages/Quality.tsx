import { Fragment, useEffect, useRef, useState } from "react";
import { api, qs } from "../api";
import { ago, bytes, num } from "../format";
import { t } from "../i18n";
import { Drawer, ErrorNote, PageHeader, Poster, RequestedBy, Seg, SwitchedOff, Tray, useFetch, useOpenTitle, useRefreshTick, useStatus } from "../components/common";
import ReleaseSearch, { AfterSwapSelect } from "../components/ReleaseSearch";
import { ACTIVE, swapsChanged, swapState } from "../components/Swaps";

type Rel = { title: string; size: number; savings: number; quality: string | null; resolution: number | null; guid: string;
  indexer_id: number; seeders: number | null; protocol: string | null; indexer: string | null; score: number };
type Item = { id: string; key: string; season: number | null; kind: string; name: string; year: number | null; library: string;
  resolution: string | null; files: number; size: number; estimate: number; play_count: number | null; last_played: number | null;
  users_count: number | null; monitored: number | null; protected: boolean; protect_reason: string | null;
  requests: { by: string; at: number | null; watched: boolean }[];
  search: { searched: number; smaller: number; total: number; release?: Rel } | null;
  swap: { id: number; state: string; message: string; progress: number | null } | null };
type Resp = { items: Item[]; limits: { movie_gb: number; episode_gb: number; target_movie_gb: number; target_episode_gb: number };
  summary: { count: number; size: number; estimate: number; searched: number; found: number; found_savings: number; protected: number; active_swaps: number } };

const MAX_SEARCH = 25;
const label = (i: Item) => `${i.name}${i.year ? ` (${i.year})` : ""}${i.season != null ? t(`, season ${i.season}`, `, sesong ${i.season}`) : ""}`;
const canSwap = (i: Item) => !!i.search?.release && !i.protected && !(i.swap && ACTIVE.includes(i.swap.state));

export default function QualityPage() {
  const tick = useRefreshTick();
  const openTitle = useOpenTitle();
  const [kind, setKind] = useState("");
  const [q, setQ] = useState("");
  const [unwatched, setUnwatched] = useState(false);
  const [minMovie, setMinMovie] = useState<string>("");
  const [minEp, setMinEp] = useState<string>("");
  const [sort, setSort] = useState("savings");
  const [reload, setReload] = useState(0);
  const [sel, setSel] = useState<string[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const [queue, setQueue] = useState<{ done: number; total: number; current: string; errors: string[] } | null>(null);
  const stop = useRef(false);
  const [confirm, setConfirm] = useState(false);
  const { data, error } = useFetch<Resp>(`/api/quality${qs({ kind, q, unwatched, min_movie_gb: minMovie, min_episode_gb: minEp, sort })}`, [tick, reload]);
  const items = data?.items ?? [];
  const s = data?.summary;
  const chosen = items.filter((i) => sel.includes(i.id));
  const ready = chosen.filter(canSwap);
  const unsearched = chosen.filter((i) => !i.search && !i.protected);
  const toggle = (id: string) => setSel(sel.includes(id) ? sel.filter((x) => x !== id) : [...sel, id]);
  const searching = !!queue && queue.done < queue.total;

  // Follow active swaps while the page is open
  useEffect(() => {
    if (!s?.active_swaps) return;
    const iv = setInterval(() => setReload((r) => r + 1), 20000);
    return () => clearInterval(iv);
  }, [s?.active_swaps]);

  const searchMany = async (list: Item[], refresh = false) => {
    const todo = list.slice(0, MAX_SEARCH);
    stop.current = false;
    const errors: string[] = [];
    for (let n = 0; n < todo.length; n++) {
      if (stop.current) break;
      const i = todo[n];
      setQueue({ done: n, total: todo.length, current: label(i), errors });
      try {
        const p = new URLSearchParams();
        if (i.season != null) p.set("season", String(i.season));
        if (refresh) p.set("refresh", "true");
        await api.get(`/api/releases/${encodeURIComponent(i.key)}?${p}`);
      } catch (e) { errors.push(`${label(i)}: ${(e as Error).message}`); }
      setReload((r) => r + 1);
    }
    setQueue({ done: todo.length, total: todo.length, current: "", errors });
  };

  return (
    <>
      <PageHeader title={t("Swap quality", "Bytt kvalitet")}
        lede={t("Large movies and seasons that can be swapped for a smaller version. Search the indexers for many titles at once, see the recommendation for each, and swap the ones you want. A swap always downloads first – the large file is not deleted until the new one is ready.",
          "Store filmer og sesonger som kan byttes til en mindre versjon. Søk i indekserne for mange titler om gangen, se anbefalingen for hver, og bytt de du vil. Byttet laster alltid ned først – den store filen slettes ikke før den nye er klar.")} />
      <ErrorNote error={error} />
      {s && data && (
        <section className="brief">
          <p className="brief-lead">
            <b>{t(`${num(s.count)} movies and seasons`, `${num(s.count)} filmer og sesonger`)}</b> {t("over the limit use", "over grensen bruker")} <b>{bytes(s.size)}</b>.{" "}
            {t(`Swapped to about ${num(data.limits.target_movie_gb, 1)} GB per movie and ${num(data.limits.target_episode_gb, 1)} GB per episode, about`,
              `Byttes de til ca. ${num(data.limits.target_movie_gb, 1)} GB per film og ${num(data.limits.target_episode_gb, 1)} GB per episode, frigjøres omtrent`)} <b>{bytes(s.estimate)}</b>{t(" is freed.", ".")}
          </p>
          <ul className="brief-points">
            <li>{s.searched
              ? <>{t(`Searched for ${num(s.searched)}. A recommended release was found for ${num(s.found)}, saving`, `Søkt for ${num(s.searched)}. Anbefalt utgivelse funnet for ${num(s.found)}, som sparer`)} <b>{bytes(s.found_savings)}</b>.</>
              : t("Nothing searched yet. Select titles and press «Search».", "Ingenting søkt ennå. Velg titler og trykk «Søk».")}</li>
            {s.active_swaps > 0 && <li>{t(`${num(s.active_swaps)} swap(s) in progress.`, `${num(s.active_swaps)} bytte(r) pågår.`)} <a href="#/activity/swaps">{t("See Activity", "Se Aktivitet")}</a></li>}
            {s.protected > 0 && <li>{t(`${num(s.protected)} are protected and cannot be swapped.`, `${num(s.protected)} er beskyttet og kan ikke byttes.`)}</li>}
          </ul>
          <p className="small muted">{t(`Limit: movies over ${num(data.limits.movie_gb, 1)} GB, seasons with episodes over ${num(data.limits.episode_gb, 1)} GB on average. Change it here or under Settings → Analysis.`,
            `Grense: filmer over ${num(data.limits.movie_gb, 1)} GB, sesonger med episoder over ${num(data.limits.episode_gb, 1)} GB i snitt. Endres her eller under Innstillinger → Analyse.`)}</p>
        </section>
      )}

      <div className="toolbar" style={{ marginTop: 24 }}>
        <Seg label={t("Type", "Type")} value={kind} onChange={setKind} options={[
          { value: "", label: t("All", "Alle") }, { value: "movie", label: t("Movies", "Filmer") }, { value: "series", label: t("Series", "Serier") },
        ]} />
        <input type="search" placeholder={t("Search", "Søk")} value={q} onChange={(e) => setQ(e.target.value)} aria-label={t("Search", "Søk")} />
        <label className="check small"><input type="checkbox" checked={unwatched} onChange={(e) => setUnwatched(e.target.checked)} />{t("Never watched only", "Bare aldri sett")}</label>
        <label className="check small">{t("Movie over", "Film over")} <input type="number" min={0} style={{ width: 64 }} placeholder={String(data?.limits.movie_gb ?? "")} value={minMovie} onChange={(e) => setMinMovie(e.target.value)} /> GB</label>
        <label className="check small">{t("Episode over", "Episode over")} <input type="number" min={0} step={0.5} style={{ width: 64 }} placeholder={String(data?.limits.episode_gb ?? "")} value={minEp} onChange={(e) => setMinEp(e.target.value)} /> GB</label>
        <select value={sort} onChange={(e) => setSort(e.target.value)} aria-label={t("Sort", "Sorter")}>
          <option value="savings">{t("Largest saving", "Størst gevinst")}</option>
          <option value="size">{t("Largest now", "Størst nå")}</option>
          <option value="watched">{t("Longest since watched", "Lengst siden sett")}</option>
          <option value="name">{t("Name", "Navn")}</option>
        </select>
      </div>
      <div className="toolbar">
        <button className="btn small" onClick={() => setSel([...new Set([...sel, ...items.filter((i) => !i.search && !i.protected).slice(0, MAX_SEARCH).map((i) => i.id)])])}>{t(`Select ${MAX_SEARCH} not searched`, `Velg ${MAX_SEARCH} usøkte`)}</button>
        <button className="btn small" onClick={() => setSel([...new Set([...sel, ...items.filter(canSwap).map((i) => i.id)])])}>{t(`Select all with a recommendation (${items.filter(canSwap).length})`, `Velg alle med anbefaling (${items.filter(canSwap).length})`)}</button>
      </div>

      {queue && (
        <div className={`notice ${queue.done === queue.total ? "ok" : ""}`}>
          {searching
            ? <>{t(`Searching ${queue.done + 1} of ${queue.total}: ${queue.current}…`, `Søker ${queue.done + 1} av ${queue.total}: ${queue.current}…`)} <button className="linkish small" onClick={() => { stop.current = true; }}>{t("Stop", "Stopp")}</button><div className="progress" style={{ marginTop: 6 }}><i style={{ width: `${(queue.done / queue.total) * 100}%` }} /></div></>
            : <>{t(`Finished searching (${queue.total}).`, `Ferdig med å søke (${queue.total}).`)} {queue.errors.length ? t(`${queue.errors.length} failed.`, `${queue.errors.length} feilet.`) : ""} <button className="linkish small" onClick={() => setQueue(null)}>{t("Hide", "Skjul")}</button></>}
          {queue.errors.length > 0 && <ul className="small muted" style={{ margin: "6px 0 0", paddingLeft: 16 }}>{queue.errors.slice(0, 5).map((e) => <li key={e}>{e}</li>)}</ul>}
        </div>
      )}

      <div className="table-wrap">
        <table>
          <thead><tr><th style={{ width: 28 }} /><th>{t("Title", "Tittel")}</th><th className="r">{t("Now", "Nå")}</th><th>{t("Recommended smaller version", "Anbefalt mindre versjon")}</th><th className="r">{t("Saves", "Sparer")}</th><th>{t("Status", "Status")}</th></tr></thead>
          <tbody>
            {items.map((i) => {
              const r = i.search?.release;
              const sw = i.swap;
              const [swl, swc] = sw ? swapState(sw.state) : ["", ""];
              return (
                <Fragment key={i.id}>
                  <tr className="row">
                    <td>{!i.protected && <input type="checkbox" checked={sel.includes(i.id)} onChange={() => toggle(i.id)} aria-label={t(`Select ${label(i)}`, `Velg ${label(i)}`)} />}</td>
                    <td className="title-cell">
                      <div style={{ display: "flex", gap: 10 }}>
                        <Poster k={i.key} title={i.name} />
                        <div>
                          <button className="linkish" style={{ fontWeight: 600 }} onClick={() => openTitle(i.key)}>{i.name}{i.year ? ` (${i.year})` : ""}</button>
                          {i.season != null && <span> · {t("Season", "Sesong")} {i.season}</span>}
                          <small>{[i.resolution, i.season != null ? t(`${i.files} episodes`, `${i.files} episoder`) : null, i.play_count ? t(`watched ${ago(i.last_played)}`, `sett ${ago(i.last_played)}`) : t("never watched", "aldri sett"), i.monitored ? t("monitored", "overvåket") : t("not monitored", "ikke overvåket")].filter(Boolean).join(", ")}</small>
                          <small><RequestedBy requests={i.requests} /></small>
                          {i.protected && <small className="muted">{t("Protected:", "Beskyttet:")} {i.protect_reason}</small>}
                        </div>
                      </div>
                    </td>
                    <td className="r num">{bytes(i.size)}</td>
                    <td className="small" style={{ maxWidth: 360 }}>
                      {r ? <>
                        <span style={{ wordBreak: "break-word" }}>{r.title}</span>
                        <div className="muted">{bytes(r.size)}, {r.quality}{r.protocol === "torrent" ? t(`, ${r.seeders ?? 0} seeders`, `, ${r.seeders ?? 0} delere`) : r.protocol === "usenet" ? ", Usenet" : ""}</div>
                      </> : i.search ? <span className="muted">{t(`None recommended (${i.search.smaller} smaller found)`, `Ingen anbefalt (${i.search.smaller} mindre funnet)`)}</span> : <span className="muted">{t("Not searched", "Ikke søkt")}</span>}
                      <div><button className="linkish small" onClick={() => setOpen(open === i.id ? null : i.id)}>{open === i.id ? t("Hide alternatives", "Skjul alternativer") : i.search ? t("See all alternatives", "Se alle alternativer") : t("Search now", "Søk nå")}</button>
                        {i.search && <span className="faint small"> · {t("searched", "søkt")} {ago(i.search.searched)}</span>}</div>
                    </td>
                    <td className="r num" style={{ fontWeight: 600 }}>{r ? bytes(r.savings) : <span className="muted" title={t("Estimate before searching", "Anslag før søk")}>~{bytes(i.estimate)}</span>}</td>
                    <td className="small" style={{ minWidth: 140 }}>
                      {sw && <><span className={`pill ${swc}`}>{swl}</span>
                        {sw.state === "downloading" && sw.progress != null && <div className="progress" style={{ marginTop: 4 }}><i style={{ width: `${sw.progress * 100}%` }} /></div>}
                        {!ACTIVE.includes(sw.state) && sw.state !== "done" && <div className="muted" style={{ marginTop: 4 }}>{sw.message}</div>}</>}
                    </td>
                  </tr>
                  {open === i.id && (
                    <tr className="detail"><td colSpan={6}><ReleaseSearch titleKey={i.key} season={i.season ?? undefined} autoStart /></td></tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      {data && items.length === 0 && <div className="empty">{t("No movies or seasons over the limit in this view.", "Ingen filmer eller sesonger over grensen i dette utvalget.")}</div>}

      {sel.length > 0 && (
        <Tray figure={bytes(ready.reduce((x, i) => x + (i.search!.release!.savings), 0))}
          note={t(`saved by ${ready.length} with a recommendation, ${sel.length} selected`, `spares av ${ready.length} med anbefaling, ${sel.length} valgt`)}>
          <button className="btn" onClick={() => setSel([])}>{t("Clear", "Tøm")}</button>
          <button className="btn" disabled={searching} onClick={() => searchMany(unsearched.length ? unsearched : chosen, !unsearched.length)}>
            {unsearched.length ? t(`Search ${Math.min(unsearched.length, MAX_SEARCH)} not searched`, `Søk etter ${Math.min(unsearched.length, MAX_SEARCH)} usøkte`) : t(`Search again (${Math.min(chosen.length, MAX_SEARCH)})`, `Søk på nytt (${Math.min(chosen.length, MAX_SEARCH)})`)}</button>
          <button className="btn primary" disabled={ready.length === 0} onClick={() => setConfirm(true)}>{t(`Swap ${ready.length}…`, `Bytt ${ready.length}…`)}</button>
        </Tray>
      )}
      {confirm && <ConfirmSwap items={ready} onClose={() => setConfirm(false)} onDone={() => { setSel([]); setReload((r) => r + 1); swapsChanged(); }} />}
    </>
  );
}

function ConfirmSwap({ items, onClose, onDone }: { items: Item[]; onClose: () => void; onDone: () => void }) {
  const status = useStatus();
  const [after, setAfter] = useState("none");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [res, setRes] = useState<{ results: { key: string; season: number | null; ok: boolean; error?: string }[]; started: number; failed: number } | null>(null);
  const services = [...new Set(items.map((i) => (i.season != null ? "sonarr" : "radarr")))];
  const total = items.reduce((x, i) => x + i.search!.release!.savings, 0);
  const download = items.reduce((x, i) => x + i.search!.release!.size, 0);
  const run = async () => {
    setBusy(true); setError(null);
    try {
      setRes(await api.post("/api/swaps/batch", { after_swap: after,
        items: items.map((i) => ({ key: i.key, season: i.season, guid: i.search!.release!.guid, indexer_id: i.search!.release!.indexer_id })) }));
      onDone();
    } catch (e) { setError(String((e as Error).message)); } finally { setBusy(false); }
  };
  const name = (k: string, s: number | null) => { const i = items.find((x) => x.key === k && x.season === s); return i ? label(i) : k; };
  return (
    <Drawer label={t("Swap to smaller versions", "Bytt til mindre versjoner")} onClose={onClose} busy={busy}>
      {res ? (
        <>
          <h1>{res.failed ? t("Partly started", "Delvis startet") : t("Started", "Startet")}</h1>
          <p className="lede">{t(`${res.started} swap(s) sent to Radarr/Sonarr. The large files stay until the new ones are downloaded and can be imported. Follow them here or under Activity.`,
            `${res.started} bytte(r) er sendt til Radarr/Sonarr. De store filene blir liggende til de nye er ferdig nedlastet og kan importeres. Følg med her eller under Aktivitet.`)}</p>
          <table className="compact"><tbody>{res.results.map((r) => <tr key={r.key + r.season}><td><i className={`dot ${r.ok ? "ok" : "bad"}`} />{name(r.key, r.season)}</td><td className="small muted">{r.ok ? t("Sent for download", "Sendt til nedlasting") : r.error}</td></tr>)}</tbody></table>
          <p><button className="btn primary" onClick={onClose}>{t("Done", "Ferdig")}</button></p>
        </>
      ) : (
        <>
          <h1>{t(`Swap ${items.length} to smaller versions`, `Bytt ${items.length} til mindre versjoner`)}</h1>
          {error && <div className="notice err">{error}</div>}
          {status && !status.actions_enabled ? <SwitchedOff what="services" onClose={onClose} /> : (
            <>
              <p className="lede">{t("Saves about", "Sparer omtrent")} <b>{bytes(total)}</b>. {t(`Radarr/Sonarr download ${bytes(download)} first, so make sure there is room for it in the downloads folder.`, `Radarr/Sonarr laster ned ${bytes(download)} først, så sørg for at det er plass til det i nedlastingsmappen.`)}</p>
              <ol className="small" style={{ paddingLeft: 18 }}>
                <li>{t("The chosen releases are sent to Radarr/Sonarr and downloaded. The large files stay.", "De valgte utgivelsene sendes til Radarr/Sonarr og lastes ned. De store filene blir liggende.")}</li>
                <li>{t("When a download is finished and is only «not an upgrade», the old file is deleted through Radarr/Sonarr and the new one imported.", "Når en nedlasting er ferdig og bare er «ikke en oppgradering», slettes den gamle filen via Radarr/Sonarr og den nye importeres.")}</li>
                <li>{t("If a file has other rejections, that swap stops and the old file is untouched.", "Har filen andre innvendinger, stopper det byttet og den gamle filen er urørt.")}</li>
              </ol>
              <AfterSwapSelect service={services.length === 1 ? services[0] : null} value={after} onChange={setAfter} />
              {services.length > 1 && <p className="small muted" style={{ margin: "4px 0 0" }}>{t("Changing the quality profile can only be chosen when all selected are movies or all are series.", "Bytte av kvalitetsprofil kan bare velges når alle valgte er filmer eller alle er serier.")}</p>}
              <table className="compact" style={{ marginTop: 16 }}><tbody>{items.map((i) => (
                <tr key={i.id}><td>{label(i)}<div className="small muted" style={{ wordBreak: "break-word" }}>{i.search!.release!.title}</div></td>
                  <td className="r num small">{bytes(i.size)} → {bytes(i.search!.release!.size)}</td></tr>
              ))}</tbody></table>
              {items.length > 10 && <div className="notice" style={{ marginTop: 12 }}>{t("Many downloads at once. Radarr/Sonarr and the download client handle the queue, but it can take a while.", "Mange nedlastinger samtidig. Radarr/Sonarr og nedlastingsklienten håndterer køen, men det kan ta tid.")}</div>}
              <p style={{ marginTop: 20 }}><button className="btn primary" onClick={run} disabled={busy}>{busy ? t("Starting…", "Starter…") : t(`Confirm: swap ${items.length} (saves ${bytes(total)})`, `Bekreft: bytt ${items.length} (sparer ${bytes(total)})`)}</button></p>
            </>
          )}
        </>
      )}
    </Drawer>
  );
}
