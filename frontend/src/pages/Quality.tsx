import { Fragment, useEffect, useRef, useState } from "react";
import { api, qs } from "../api";
import { ago, bytes, num } from "../format";
import { ErrorNote, Poster, RequestedBy, useFetch, useOpenTitle, useRefreshTick } from "../components/common";
import ReleaseSearch from "../components/ReleaseSearch";
import { SWAP_STATE, swapsChanged } from "../components/Swaps";

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

const ACTIVE = ["venter", "laster_ned", "klar", "importerer"];
const MAX_SEARCH = 25;
const label = (i: Item) => `${i.name}${i.year ? ` (${i.year})` : ""}${i.season != null ? `, sesong ${i.season}` : ""}`;
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
  const params = { kind, q, unwatched: unwatched ? "true" : "", min_movie_gb: minMovie, min_episode_gb: minEp, sort };
  const { data, error } = useFetch<Resp>(`/api/quality${qs(params)}`, [tick, reload]);
  const items = data?.items ?? [];
  const s = data?.summary;
  const chosen = items.filter((i) => sel.includes(i.id));
  const ready = chosen.filter(canSwap);
  const unsearched = chosen.filter((i) => !i.search && !i.protected);
  const toggle = (id: string) => setSel(sel.includes(id) ? sel.filter((x) => x !== id) : [...sel, id]);

  // Følg aktive bytter mens siden er åpen
  useEffect(() => {
    if (!s?.active_swaps) return;
    const t = setInterval(() => setReload((r) => r + 1), 20000);
    return () => clearInterval(t);
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
      <h1>Bytt kvalitet</h1>
      <p className="lede">Store filmer og sesonger som kan byttes til en mindre versjon. Søk i indekserne for mange titler om gangen, se anbefalingen for hver, og bytt de du vil med ett klikk. Byttet laster alltid ned først – den store filen slettes ikke før den nye er klar.</p>
      <ErrorNote error={error} />
      {s && data && (
        <section className="brief">
          <p className="brief-lead">
            <b>{num(s.count)} {s.count === 1 ? "film eller sesong" : "filmer og sesonger"}</b> over grensen bruker <b>{bytes(s.size)}</b>.
            Byttes de til ca. {data.limits.target_movie_gb.toLocaleString("nb-NO")} GB per film og {data.limits.target_episode_gb.toLocaleString("nb-NO")} GB per episode, frigjøres omtrent <b>{bytes(s.estimate)}</b>.
          </p>
          <ul className="brief-points">
            <li>{s.searched ? <>Søkt for {num(s.searched)}. Anbefalt utgivelse funnet for {num(s.found)}, som sparer <b>{bytes(s.found_savings)}</b>.</> : "Ingen er søkt ennå. Velg titler og trykk «Søk etter valgte»."}</li>
            {s.active_swaps > 0 && <li>{num(s.active_swaps)} bytte(r) pågår. Se også <a href="#/jobber">Jobber</a>.</li>}
            {s.protected > 0 && <li>{num(s.protected)} er beskyttet og kan ikke byttes.</li>}
          </ul>
          <p className="small muted">Grense: filmer over {data.limits.movie_gb.toLocaleString("nb-NO")} GB, sesonger med episoder over {data.limits.episode_gb.toLocaleString("nb-NO")} GB i snitt. Endres her eller under Innstillinger → Analyse.</p>
        </section>
      )}

      <div className="toolbar" style={{ marginTop: 24 }}>
        <div className="seg" role="group" aria-label="Type">
          {[["", "Alle"], ["movie", "Filmer"], ["series", "Serier"]].map(([v, l]) => (
            <button key={v} aria-pressed={kind === v} onClick={() => setKind(v)}>{l}</button>
          ))}
        </div>
        <input type="search" placeholder="Søk" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Søk" />
        <label className="check small"><input type="checkbox" checked={unwatched} onChange={(e) => setUnwatched(e.target.checked)} />Bare aldri sett</label>
        <label className="check small">Film over <input type="number" min={0} style={{ width: 64 }} placeholder={String(data?.limits.movie_gb ?? "")} value={minMovie} onChange={(e) => setMinMovie(e.target.value)} /> GB</label>
        <label className="check small">Episode over <input type="number" min={0} step={0.5} style={{ width: 64 }} placeholder={String(data?.limits.episode_gb ?? "")} value={minEp} onChange={(e) => setMinEp(e.target.value)} /> GB</label>
        <select value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sorter">
          <option value="savings">Størst gevinst</option>
          <option value="size">Størst nå</option>
          <option value="watched">Lengst siden sett</option>
          <option value="name">Navn</option>
        </select>
      </div>
      <div className="toolbar">
        <button className="btn small" onClick={() => setSel([...new Set([...sel, ...items.filter(canSwap).map((i) => i.id)])])}>Velg alle med anbefaling ({items.filter(canSwap).length})</button>
        <button className="btn small" onClick={() => setSel([...new Set([...sel, ...items.filter((i) => !i.search && !i.protected).slice(0, MAX_SEARCH).map((i) => i.id)])])}>Velg {MAX_SEARCH} usøkte</button>
        {sel.length > 0 && <button className="btn small" onClick={() => setSel([])}>Fjern valg</button>}
      </div>

      {queue && (
        <div className={`notice ${queue.done === queue.total ? "ok" : ""}`}>
          {queue.done < queue.total
            ? <>Søker {queue.done + 1} av {queue.total}: {queue.current}… <button className="linkish small" onClick={() => { stop.current = true; }}>Stopp</button><div className="progress" style={{ marginTop: 6 }}><i style={{ width: `${(queue.done / queue.total) * 100}%` }} /></div></>
            : <>Ferdig med å søke ({queue.total}). {queue.errors.length ? `${queue.errors.length} feilet.` : ""} <button className="linkish small" onClick={() => setQueue(null)}>Skjul</button></>}
          {queue.errors.length > 0 && <ul className="small muted" style={{ margin: "6px 0 0", paddingLeft: 16 }}>{queue.errors.slice(0, 5).map((e) => <li key={e}>{e}</li>)}</ul>}
        </div>
      )}

      <div className="table-wrap">
        <table>
          <thead><tr><th style={{ width: 28 }} /><th>Tittel</th><th className="r">Nå</th><th>Anbefalt mindre versjon</th><th className="r">Sparer</th><th>Status</th></tr></thead>
          <tbody>
            {items.map((i) => {
              const r = i.search?.release;
              const sw = i.swap;
              const [swl, swc] = sw ? SWAP_STATE[sw.state] ?? [sw.state, ""] : ["", ""];
              return (
                <Fragment key={i.id}>
                  <tr className="row">
                    <td>{!i.protected && <input type="checkbox" checked={sel.includes(i.id)} onChange={() => toggle(i.id)} aria-label={`Velg ${label(i)}`} />}</td>
                    <td className="title-cell">
                      <div style={{ display: "flex", gap: 10 }}>
                        <Poster k={i.key} title={i.name} />
                        <div>
                          <button className="linkish" style={{ textAlign: "left", fontWeight: 600 }} onClick={() => openTitle(i.key)}>{i.name}{i.year ? ` (${i.year})` : ""}</button>
                          {i.season != null && <span> · Sesong {i.season}</span>}
                          <small>{[i.resolution, i.season != null ? `${i.files} episoder` : null, i.play_count ? `sett ${ago(i.last_played)}` : "aldri sett", i.monitored ? "overvåket" : "ikke overvåket"].filter(Boolean).join(", ")}</small>
                          <small><RequestedBy requests={i.requests} /></small>
                          {i.protected && <small className="muted">Beskyttet: {i.protect_reason}</small>}
                        </div>
                      </div>
                    </td>
                    <td className="r num">{bytes(i.size)}</td>
                    <td className="small" style={{ maxWidth: 360 }}>
                      {r ? <>
                        <span style={{ wordBreak: "break-word" }}>{r.title}</span>
                        <div className="muted">{bytes(r.size)}, {r.quality}{r.protocol === "torrent" ? `, ${r.seeders ?? 0} delere` : r.protocol === "usenet" ? ", Usenet" : ""}</div>
                      </> : i.search ? <span className="muted">Ingen anbefalt ({i.search.smaller} mindre funnet)</span> : <span className="muted">Ikke søkt</span>}
                      <div><button className="linkish small" onClick={() => setOpen(open === i.id ? null : i.id)}>{open === i.id ? "Skjul alternativer" : i.search ? "Se alle alternativer" : "Søk nå"}</button>
                        {i.search && <span className="faint small"> · søkt {ago(i.search.searched)}</span>}</div>
                    </td>
                    <td className="r num" style={{ fontWeight: 600 }}>{r ? bytes(r.savings) : <span className="muted" title="Anslag før søk">~{bytes(i.estimate)}</span>}</td>
                    <td className="small" style={{ minWidth: 140 }}>
                      {sw && <><span className={`pill ${swc}`}>{swl}</span>
                        {sw.state === "laster_ned" && sw.progress != null && <div className="progress" style={{ marginTop: 4 }}><i style={{ width: `${sw.progress * 100}%` }} /></div>}
                        {!ACTIVE.includes(sw.state) && sw.state !== "ferdig" && <div className="muted" style={{ marginTop: 4 }}>{sw.message}</div>}</>}
                    </td>
                  </tr>
                  {open === i.id && (
                    <tr className="detail"><td colSpan={6}>
                      <ReleaseSearch titleKey={i.key} season={i.season ?? undefined} autoStart />
                    </td></tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      {data && items.length === 0 && <div className="empty">Ingen filmer eller sesonger over grensen i dette utvalget.</div>}

      {sel.length > 0 && (
        <div className="tray" role="region" aria-label="Valgte">
          <div><div className="big">{bytes(ready.reduce((x, i) => x + (i.search!.release!.savings), 0))}</div>
            <div className="small muted">spares av {ready.length} med anbefaling, {sel.length} valgt</div></div>
          <div className="grow" />
          <button className="btn" onClick={() => setSel([])}>Tøm</button>
          <button className="btn" disabled={!!queue && queue.done < queue.total} onClick={() => searchMany(unsearched.length ? unsearched : chosen, !unsearched.length)}>
            {unsearched.length ? `Søk etter ${Math.min(unsearched.length, MAX_SEARCH)} usøkte` : `Søk på nytt (${Math.min(chosen.length, MAX_SEARCH)})`}</button>
          <button className="btn primary" disabled={ready.length === 0} onClick={() => setConfirm(true)}>Bytt {ready.length}…</button>
        </div>
      )}
      {confirm && <ConfirmSwap items={ready} onClose={() => setConfirm(false)} onDone={() => { setSel([]); setReload((r) => r + 1); swapsChanged(); }} />}
    </>
  );
}

function ConfirmSwap({ items, onClose, onDone }: { items: Item[]; onClose: () => void; onDone: () => void }) {
  const [after, setAfter] = useState("none");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [res, setRes] = useState<{ results: { key: string; season: number | null; ok: boolean; error?: string }[]; started: number; failed: number } | null>(null);
  const status = useFetch<{ actions_enabled: boolean }>("/api/status", []);
  const services = [...new Set(items.map((i) => (i.season != null ? "sonarr" : "radarr")))];
  const profiles = useFetch<{ items: { id: number; name: string }[] }>(services.length === 1 ? `/api/quality-profiles/${services[0]}` : null, [services.join()]);
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
    <>
      <div className="drawer-bg" onClick={() => !busy && onClose()} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-label="Bytt til mindre versjoner">
        <button className="btn small close" onClick={onClose} disabled={busy}>Lukk</button>
        {res ? (
          <>
            <h1>{res.failed ? "Delvis startet" : "Startet"}</h1>
            <p className="lede">{res.started} bytte(r) er sendt til Radarr/Sonarr. De store filene blir liggende til de nye er ferdig nedlastet og kan importeres. Følg med her eller under Jobber.</p>
            <table className="compact"><tbody>{res.results.map((r) => <tr key={r.key + r.season}><td><i className={`dot ${r.ok ? "ok" : "bad"}`} />{name(r.key, r.season)}</td><td className="small muted">{r.ok ? "Sendt til nedlasting" : r.error}</td></tr>)}</tbody></table>
            <p><button className="btn primary" onClick={onClose}>Ferdig</button></p>
          </>
        ) : (
          <>
            <h1>Bytt {items.length} til mindre versjoner</h1>
            {error && <div className="notice err">{error}</div>}
            {status.data && !status.data.actions_enabled ? (
              <div className="notice">Bytte krever at sletting via Radarr/Sonarr er slått på under <a href="#/innstillinger" onClick={onClose}>Innstillinger → Sletting</a>.</div>
            ) : (
              <>
                <p className="lede">Sparer omtrent <b>{bytes(total)}</b>. Radarr/Sonarr laster ned {bytes(download)} først, så sørg for at det er plass til det i nedlastingsmappen.</p>
                <ol className="small" style={{ paddingLeft: 18 }}>
                  <li>De valgte utgivelsene sendes til Radarr/Sonarr og lastes ned. De store filene blir liggende.</li>
                  <li>Når en nedlasting er ferdig og bare er «ikke en oppgradering», slettes den gamle filen via Radarr/Sonarr og den nye importeres.</li>
                  <li>Har filen andre innvendinger, stopper det byttet og den gamle filen er urørt.</li>
                </ol>
                <label className="small">Etter byttet:{" "}
                  <select value={after} onChange={(e) => setAfter(e.target.value)}>
                    <option value="none">La Radarr/Sonarr være som før</option>
                    <option value="unmonitor">Avovervåk, så de ikke oppgraderes tilbake</option>
                    {profiles.data?.items.map((p) => <option key={p.id} value={`profile:${p.id}`}>Bytt kvalitetsprofil til «{p.name}»</option>)}
                  </select>
                </label>
                {services.length > 1 && <p className="small muted" style={{ margin: "4px 0 0" }}>Bytte av kvalitetsprofil kan bare velges når alle valgte er filmer eller alle er serier.</p>}
                <table className="compact" style={{ marginTop: 16 }}><tbody>{items.map((i) => (
                  <tr key={i.id}><td>{label(i)}<div className="small muted" style={{ wordBreak: "break-word" }}>{i.search!.release!.title}</div></td>
                    <td className="r num small">{bytes(i.size)} → {bytes(i.search!.release!.size)}</td></tr>
                ))}</tbody></table>
                {items.length > 10 && <div className="notice" style={{ marginTop: 12 }}>Mange nedlastinger samtidig. Radarr/Sonarr og nedlastingsklienten håndterer køen, men det kan ta tid.</div>}
                <p style={{ marginTop: 20 }}><button className="btn primary" onClick={run} disabled={busy}>{busy ? "Starter…" : `Bekreft: bytt ${items.length} (sparer ${bytes(total)})`}</button></p>
              </>
            )}
          </>
        )}
      </aside>
    </>
  );
}
