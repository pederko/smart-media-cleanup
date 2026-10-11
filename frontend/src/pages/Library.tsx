import { useEffect, useMemo, useState } from "react";
import { api, qs, Requester } from "../api";
import { ago, bytes, date, KIND_LABEL, num } from "../format";
import { ErrorNote, Poster, RequestedBy, RiskPill, useFetch, useOpenTitle, useRefreshTick } from "../components/common";
import DeleteDialog from "../components/DeleteDialog";

type Best = { id: string; kind: string; action: string; score: number; risk: string; savings: number } | null;
type Row = {
  key: string; kind: string; name: string; year: number | null; library: string; alloc: number; video_count: number;
  play_count: number; last_played: number | null; users_count: number; recent_users_count: number; added: number | null;
  protected: number; protect_reason: string | null; best_resolution: string | null; monitored: number | null;
  radarr_id: number | null; sonarr_id: number | null; requests: { by: string; at: number | null; watched: boolean }[];
  best: Best; suggestion_count: number; delete_id: string | null; delete_savings: number;
  requested_at_by_user?: number | null; watched_by_user?: boolean;
};
type Agg = { count: number; bytes: number };
type LibSummary = {
  kind: string; count: number; bytes: number; never: Agg; stale: ({ months: number } & Agg)[]; protected: Agg;
  suggested: Agg; freed: number; actions: { kind: string; count: number; freed: number }[];
  low_risk_delete: { count: number; freed: number }; requested: Agg; four_k: Agg; top: Row[]; min_score: number;
};

/** Norsk entall/flertall: n("film","filmer") */
function pl(n: number, one: string, many: string) { return `${num(n)} ${n === 1 ? one : many}`; }

function useDebounced(v: string) {
  const [d, setD] = useState(v);
  useEffect(() => { const t = setTimeout(() => setD(v), 250); return () => clearTimeout(t); }, [v]);
  return d;
}

function useCanDelete() {
  const tick = useRefreshTick();
  const s = useFetch<{ actions_enabled: boolean }>("/api/status", [tick]);
  return !!s.data?.actions_enabled;
}

/* ------------------------------------------------------------------ felles tabell */

function TitleTable({ rows, sort, order, onSort, selectable, sel, setSel, showRequested }: {
  rows: Row[]; sort: string; order: string; onSort: (c: string) => void; selectable: boolean;
  sel: string[]; setSel: (f: (s: string[]) => string[]) => void; showRequested?: boolean;
}) {
  const openTitle = useOpenTitle();
  const th = (c: string, l: string, r = false) => (
    <th className={r ? "r" : undefined}>
      <button onClick={() => onSort(c)} aria-sort={sort === c ? (order === "asc" ? "ascending" : "descending") : undefined}>
        {l}{sort === c ? (order === "asc" ? " ↑" : " ↓") : ""}
      </button>
    </th>
  );
  const deletable = rows.filter((r) => r.delete_id && !r.protected).map((r) => r.delete_id!);
  const allSel = deletable.length > 0 && deletable.every((id) => sel.includes(id));
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {selectable && <th style={{ width: 36 }}><input type="checkbox" aria-label="Velg alle synlige som kan slettes" checked={allSel}
              onChange={() => setSel((s) => allSel ? s.filter((id) => !deletable.includes(id)) : [...new Set([...s, ...deletable])])} /></th>}
            {th("name", "Tittel")}
            {showRequested && th("requested", "Etterspurt")}
            {th("size", "Størrelse", true)}
            {th("last_played", "Seing")}
            {th("score", "Anbefaling")}
            {th("savings", "Frigjøres", true)}
          </tr>
        </thead>
        <tbody>
          {rows.map((t) => (
            <tr key={t.key} className="row">
              {selectable && <td>{t.delete_id && !t.protected
                ? <input type="checkbox" checked={sel.includes(t.delete_id)} aria-label={`Velg ${t.name}`}
                    onChange={() => setSel((s) => s.includes(t.delete_id!) ? s.filter((x) => x !== t.delete_id) : [...s, t.delete_id!])} />
                : null}</td>}
              <td className="title-cell">
                <div className="with-poster">
                  <Poster k={t.key} title={t.name} size="m" />
                  <div style={{ minWidth: 0 }}>
                    <button className="btn small linkish" onClick={() => openTitle(t.key)}>{t.name}{t.year ? ` (${t.year})` : ""}</button>
                    <small>
                      {t.library}{t.best_resolution ? `, ${t.best_resolution}` : ""}
                      {t.kind === "series" ? `, ${t.video_count} episoder` : ""}
                      {t.radarr_id != null ? (t.monitored ? ", overvåket" : ", Radarr") : t.sonarr_id != null ? (t.monitored ? ", overvåket" : ", Sonarr") : ""}
                      {t.protected ? ", beskyttet" : ""}
                    </small>
                    {!showRequested && t.requests?.length ? <small><RequestedBy requests={t.requests} /></small> : null}
                  </div>
                </div>
              </td>
              {showRequested && (
                <td className="small">{date(t.requested_at_by_user)}
                  <div className={t.watched_by_user ? "muted" : "req"}>{t.watched_by_user ? "har sett den" : "har ikke sett den"}</div>
                </td>
              )}
              <td className="r num">{bytes(t.alloc)}</td>
              <td className="small">
                {t.play_count ? <>{t.play_count} avspilling{t.play_count === 1 ? "" : "er"}<div className="muted">sist {ago(t.last_played)}, {t.users_count} bruker{t.users_count === 1 ? "" : "e"}</div></> : <span className="muted">Aldri sett</span>}
              </td>
              <td className="small">
                {t.protected ? <span className="muted">Beskyttet</span> : t.best ? (
                  <>
                    <div>{t.best.action} <span className="faint">({Math.round(t.best.score)})</span></div>
                    <RiskPill risk={t.best.risk} />
                    {t.suggestion_count > 1 && <span className="faint"> +{t.suggestion_count - 1}</span>}
                  </>
                ) : <span className="muted">Behold</span>}
              </td>
              <td className="r num" style={{ fontWeight: 600 }}>{t.best ? bytes(t.best.savings) : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SelectionTray({ sel, setSel, canDelete }: { sel: string[]; setSel: (f: (s: string[]) => string[]) => void; canDelete: boolean }) {
  const [info, setInfo] = useState<{ freed: number } | null>(null);
  const [deleting, setDeleting] = useState(false);
  useEffect(() => {
    if (!sel.length) { setInfo(null); return; }
    api.post<{ freed: number }>("/api/selection", { ids: sel }).then(setInfo).catch(() => setInfo(null));
  }, [sel]);
  if (!sel.length) return null;
  return (
    <>
      <div className="tray" role="region" aria-label="Valgte titler">
        <div><div className="big">{bytes(info?.freed ?? 0)}</div><div className="small muted">frigjøres ved å slette {sel.length} valgte</div></div>
        <div className="grow" />
        <button className="btn" onClick={() => setSel(() => [])}>Tøm utvalget</button>
        {!canDelete && <span className="small muted">Sletting er av – slå den på under <a href="#/innstillinger">Innstillinger</a>.</span>}
        <button className="btn danger" onClick={() => setDeleting(true)}>Slett valgte…</button>
      </div>
      {deleting && <DeleteDialog ids={sel} onClose={() => setDeleting(false)} onDone={(done) => setSel((s) => s.filter((id) => !done.includes(id)))} />}
    </>
  );
}

/* ------------------------------------------------------------------ filmer / serier */

export function LibraryPage({ kind }: { kind: "movie" | "series" }) {
  const tick = useRefreshTick();
  const openTitle = useOpenTitle();
  const canDelete = useCanDelete();
  const [q, setQ] = useState("");
  const [view, setView] = useState("suggested");
  const [sort, setSort] = useState("score");
  const [order, setOrder] = useState("desc");
  const [limit, setLimit] = useState(100);
  const [sel, setSel] = useState<string[]>([]);
  const dq = useDebounced(q);
  useEffect(() => { setSel([]); setView("suggested"); setSort("score"); setOrder("desc"); setQ(""); }, [kind]);
  const { data, error } = useFetch<{ summary: LibSummary; total: number; total_bytes: number; items: Row[] }>(
    `/api/library/${kind}${qs({ view, q: dq, sort, order, limit })}`, [tick]);
  const onSort = (c: string) => { if (sort === c) setOrder(order === "desc" ? "asc" : "desc"); else { setSort(c); setOrder(c === "name" ? "asc" : "desc"); } };
  const s = data?.summary;
  const word = kind === "movie" ? "filmer" : "serier";
  const one = kind === "movie" ? "film" : "serie";
  const stale24 = s?.stale.find((x) => x.months === 24) ?? s?.stale[1];

  const views: [string, string][] = [
    ["suggested", "Har forslag"], ["low_risk", "Trygge slettinger"], ["never", "Aldri sett"],
    ...(s?.stale.map((x) => [`stale${x.months}`, `Ikke sett ${x.months} mnd`] as [string, string]) ?? []),
    ...(kind === "movie" ? [["4k", "4K"] as [string, string]] : []),
    ["requested", "Etterspurt"], ["protected", "Beskyttet"], ["all", "Alle"],
  ];

  return (
    <>
      <h1>{kind === "movie" ? "Filmer" : "Serier"}</h1>
      <ErrorNote error={error} />
      {s && (
        <section className="brief">
          <p className="brief-lead">
            {num(s.count)} {s.count === 1 ? one : word} bruker <b>{bytes(s.bytes)}</b>.{" "}
            {s.suggested.count > 0
              ? <>{num(s.suggested.count)} av dem har forslag over prioritet {s.min_score}, og til sammen kan <b>{bytes(s.freed)}</b> frigjøres.</>
              : <>Ingen har forslag over prioritet {s.min_score}.</>}
          </p>
          <ul className="brief-points">
            {s.never.count > 0 && <li><button className="linkish" onClick={() => setView("never")}>{pl(s.never.count, one, word)}</button> er aldri sett ({bytes(s.never.bytes)}).</li>}
            {stale24 && stale24.count > 0 && <li><button className="linkish" onClick={() => setView(`stale${stale24.months}`)}>{pl(stale24.count, one, word)}</button> er ikke sett på {stale24.months} måneder ({bytes(stale24.bytes)}).</li>}
            {s.low_risk_delete.count > 0 && <li>Tryggest å starte med: <button className="linkish" onClick={() => setView("low_risk")}>{pl(s.low_risk_delete.count, "sletting", "slettinger")} med lav risiko</button>, som frigjør {bytes(s.low_risk_delete.freed)}.</li>}
            {kind === "movie" && s.four_k.count > 0 && <li><button className="linkish" onClick={() => setView("4k")}>{pl(s.four_k.count, "film", "filmer")} i 4K</button> bruker {bytes(s.four_k.bytes)}. Se «Erstatt med mindre».</li>}
            {s.protected.count > 0 && <li>{num(s.protected.count)} er beskyttet og vises aldri som forslag.</li>}
          </ul>
          {s.actions.length > 0 && (
            <div className="chips">
              {s.actions.map((a) => (
                <span key={a.kind} className="chip"><b>{KIND_LABEL[a.kind] ?? a.kind}</b> {a.count} stk, {bytes(a.freed)}</span>
              ))}
            </div>
          )}
          {s.top.length > 0 && (
            <>
              <h2 style={{ marginTop: 26 }}>Bør ses på først</h2>
              <div className="top-cards">
                {s.top.map((t) => (
                  <button key={t.key} className="top-card" onClick={() => openTitle(t.key)}>
                    <Poster k={t.key} title={t.name} size="l" />
                    <span className="tc-name">{t.name}</span>
                    <span className="small muted">{t.best?.action}, {bytes(t.best?.savings)}</span>
                    {t.best && <RiskPill risk={t.best.risk} />}
                  </button>
                ))}
              </div>
            </>
          )}
        </section>
      )}

      <div className="toolbar" style={{ marginTop: 32 }}>
        <input type="search" placeholder={`Søk i ${word}`} value={q} onChange={(e) => setQ(e.target.value)} aria-label="Søk" />
        <div className="seg wrap" role="group" aria-label="Utvalg">
          {views.map(([v, l]) => <button key={v} aria-pressed={view === v} onClick={() => { setView(v); setLimit(100); }}>{l}</button>)}
        </div>
      </div>
      {data && <p className="small muted">{num(data.total)} {data.total === 1 ? one : word}, {bytes(data.total_bytes)}.</p>}
      {data && <TitleTable rows={data.items} sort={sort} order={order} onSort={onSort} selectable sel={sel} setSel={setSel} />}
      {data && data.items.length === 0 && <div className="empty">Ingen {word} i dette utvalget.</div>}
      {data && data.total > data.items.length && <p><button className="btn" onClick={() => setLimit(limit + 200)}>Vis flere ({num(data.total - data.items.length)} igjen)</button></p>}
      <SelectionTray sel={sel} setSel={setSel} canDelete={canDelete} />
    </>
  );
}

/* ------------------------------------------------------------------ brukere */

export function UsersPage() {
  const tick = useRefreshTick();
  const { data, error } = useFetch<{ items: Requester[]; seerr?: { ok: boolean; message: string } }>("/api/requesters", [tick]);
  return (
    <>
      <h1>Brukere</h1>
      <p className="lede">Hvem som har bedt om hva i Seerr, og hvor mye av det de faktisk har sett. Åpne en bruker for detaljer og opprydding.</p>
      <ErrorNote error={error} />
      {data && data.items.length === 0 && (
        <div className="empty">Ingen forespørsler funnet. Koble til Seerr under Innstillinger og kjør en full oppdatering.</div>
      )}
      {data && data.items.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Bruker</th><th className="r">Titler</th><th className="r">Plass</th><th className="r">Ikke sett av brukeren</th><th className="r">Aldri sett av noen</th><th>Siste forespørsel</th></tr></thead>
            <tbody>
              {data.items.map((r) => {
                const pct = r.titles ? Math.round((r.not_watched_by_requester / r.titles) * 100) : 0;
                return (
                  <tr key={r.name} className="row">
                    <td><a className="title-link" href={`#/brukere/${encodeURIComponent(r.name)}`}>{r.name}</a></td>
                    <td className="r">{r.titles}</td>
                    <td className="r num">{bytes(r.bytes)}</td>
                    <td className="r num">{r.not_watched_by_requester} <span className="faint">({pct} %, {bytes(r.not_watched_bytes)})</span></td>
                    <td className="r num">{r.never_watched} <span className="faint">({bytes(r.never_watched_bytes)})</span></td>
                    <td className="muted small">{date(r.last_request)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

type UserSummary = {
  name: string; count: number; bytes: number; movies: Agg; series: Agg; watched_by_user: Agg; unwatched_by_user: Agg;
  unwatched_older_than_12m: Agg; never_watched: Agg; unwatched_delete: { count: number; freed: number };
  first_request: number | null; last_request: number | null;
};

export function UserPage({ name }: { name: string }) {
  const tick = useRefreshTick();
  const canDelete = useCanDelete();
  const [view, setView] = useState("unwatched");
  const [sort, setSort] = useState("requested");
  const [order, setOrder] = useState("desc");
  const [sel, setSel] = useState<string[]>([]);
  const { data, error } = useFetch<{ summary: UserSummary; total: number; items: Row[] }>(
    `/api/requesters/${encodeURIComponent(name)}${qs({ view, sort, order })}`, [tick, name]);
  const onSort = (c: string) => { if (sort === c) setOrder(order === "desc" ? "asc" : "desc"); else { setSort(c); setOrder(c === "name" ? "asc" : "desc"); } };
  const s = data?.summary;
  const unwatchedDeletable = useMemo(() => (data?.items ?? []).filter((t) => !t.watched_by_user && t.delete_id && !t.protected).map((t) => t.delete_id!), [data]);
  const pct = s && s.count ? Math.round((s.watched_by_user.count / s.count) * 100) : 0;

  return (
    <>
      <p className="small"><a href="#/brukere">Brukere</a></p>
      <h1>{name}</h1>
      <ErrorNote error={error} />
      {s && (
        <section className="brief">
          <p className="brief-lead">
            {name} har bedt om <b>{pl(s.count, "tittel", "titler")}</b> ({pl(s.movies.count, "film", "filmer")} og {pl(s.series.count, "serie", "serier")}) som bruker <b>{bytes(s.bytes)}</b>
            {s.first_request ? <>, fra {date(s.first_request)} til {date(s.last_request)}</> : null}.{" "}
            {name} har sett {s.watched_by_user.count} av dem ({pct} %).
          </p>
          <ul className="brief-points">
            <li><button className="linkish" onClick={() => setView("unwatched")}>{pl(s.unwatched_by_user.count, "tittel", "titler")}</button> er ikke sett av {name} ({bytes(s.unwatched_by_user.bytes)}).</li>
            {s.unwatched_older_than_12m.count > 0 && <li><button className="linkish" onClick={() => setView("unwatched_old")}>{num(s.unwatched_older_than_12m.count)}</button> av dem ble etterspurt for over 12 måneder siden ({bytes(s.unwatched_older_than_12m.bytes)}).</li>}
            {s.never_watched.count > 0 && <li><button className="linkish" onClick={() => setView("never")}>{pl(s.never_watched.count, "tittel", "titler")}</button> er ikke sett av noen ({bytes(s.never_watched.bytes)}).</li>}
            {s.unwatched_delete.count > 0 && <li>Sletter du det {name} ikke har sett, og som kan slettes fra appen ({pl(s.unwatched_delete.count, "tittel", "titler")}), frigjøres <b>{bytes(s.unwatched_delete.freed)}</b>.</li>}
          </ul>
        </section>
      )}
      <div className="toolbar" style={{ marginTop: 32 }}>
        <div className="seg wrap" role="group" aria-label="Utvalg">
          {[["unwatched", `Ikke sett av ${name}`], ["unwatched_old", "Ikke sett, over 12 mnd"], ["never", "Ikke sett av noen"], ["watched", "Sett"], ["all", "Alle"]].map(([v, l]) => (
            <button key={v} aria-pressed={view === v} onClick={() => setView(v)}>{l}</button>
          ))}
        </div>
        {unwatchedDeletable.length > 0 && (
          <button className="btn small" onClick={() => setSel((cur) => [...new Set([...cur, ...unwatchedDeletable])])}>Velg alle ikke sette her ({unwatchedDeletable.length})</button>
        )}
      </div>
      {data && <TitleTable rows={data.items} sort={sort} order={order} onSort={onSort} selectable sel={sel} setSel={setSel} showRequested />}
      {data && data.items.length === 0 && <div className="empty">Ingen titler i dette utvalget.</div>}
      <SelectionTray sel={sel} setSel={setSel} canDelete={canDelete} />
    </>
  );
}
