import { useEffect, useMemo, useState } from "react";
import { api, qs, Requester } from "../api";
import { ago, bytes, date, kindLabel, num } from "../format";
import { plural, t } from "../i18n";
import { ErrorNote, PageHeader, Poster, RequestedBy, RiskPill, Seg, Tray, useFetch, useOpenTitle, useRefreshTick, useStatus } from "../components/common";
import DeleteDialog from "../components/DeleteDialog";

type Best = { id: string; kind: string; label: string; score: number; risk: string; savings: number } | null;
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

function useDebounced(v: string) {
  const [d, setD] = useState(v);
  useEffect(() => { const x = setTimeout(() => setD(v), 250); return () => clearTimeout(x); }, [v]);
  return d;
}

/* ------------------------------------------------------------------ shared table */

function TitleTable({ rows, sort, order, onSort, sel, setSel, showRequested }: {
  rows: Row[]; sort: string; order: string; onSort: (c: string) => void;
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
            <th style={{ width: 36 }}><input type="checkbox" aria-label={t("Select all visible that can be deleted", "Velg alle synlige som kan slettes")} checked={allSel}
              onChange={() => setSel((s) => allSel ? s.filter((id) => !deletable.includes(id)) : [...new Set([...s, ...deletable])])} /></th>
            {th("name", t("Title", "Tittel"))}
            {showRequested && th("requested", t("Requested", "Etterspurt"))}
            {th("size", t("Size", "Størrelse"), true)}
            {th("last_played", t("Watched", "Seing"))}
            {th("score", t("Recommendation", "Anbefaling"))}
            {th("savings", t("Freed", "Frigjøres"), true)}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key} className="row">
              <td>{r.delete_id && !r.protected
                ? <input type="checkbox" checked={sel.includes(r.delete_id)} aria-label={t(`Select ${r.name}`, `Velg ${r.name}`)}
                    onChange={() => setSel((s) => s.includes(r.delete_id!) ? s.filter((x) => x !== r.delete_id) : [...s, r.delete_id!])} />
                : null}</td>
              <td className="title-cell">
                <div className="with-poster">
                  <Poster k={r.key} title={r.name} size="m" />
                  <div style={{ minWidth: 0 }}>
                    <button className="linkish" style={{ fontWeight: 560 }} onClick={() => openTitle(r.key)}>{r.name}{r.year ? ` (${r.year})` : ""}</button>
                    <small>
                      {r.library}{r.best_resolution ? `, ${r.best_resolution}` : ""}
                      {r.kind === "series" ? t(`, ${r.video_count} episodes`, `, ${r.video_count} episoder`) : ""}
                      {r.radarr_id != null || r.sonarr_id != null ? (r.monitored ? t(", monitored", ", overvåket") : r.radarr_id != null ? ", Radarr" : ", Sonarr") : ""}
                      {r.protected ? t(", protected", ", beskyttet") : ""}
                    </small>
                    {!showRequested && r.requests?.length ? <small><RequestedBy requests={r.requests} /></small> : null}
                  </div>
                </div>
              </td>
              {showRequested && (
                <td className="small">{date(r.requested_at_by_user)}
                  <div className={r.watched_by_user ? "muted" : "req"}>{r.watched_by_user ? t("has watched it", "har sett den") : t("has not watched it", "har ikke sett den")}</div>
                </td>
              )}
              <td className="r num">{bytes(r.alloc)}</td>
              <td className="small">
                {r.play_count
                  ? <>{plural(r.play_count, ["play", "plays"], ["avspilling", "avspillinger"])}<div className="muted">{t("last", "sist")} {ago(r.last_played)}, {plural(r.users_count, ["user", "users"], ["bruker", "brukere"])}</div></>
                  : <span className="muted">{t("Never watched", "Aldri sett")}</span>}
              </td>
              <td className="small">
                {r.protected ? <span className="muted">{t("Protected", "Beskyttet")}</span> : r.best ? (
                  <>
                    <div>{r.best.label} <span className="faint">({Math.round(r.best.score)})</span></div>
                    <RiskPill risk={r.best.risk} />
                    {r.suggestion_count > 1 && <span className="faint"> +{r.suggestion_count - 1}</span>}
                  </>
                ) : <span className="muted">{t("Keep", "Behold")}</span>}
              </td>
              <td className="r num" style={{ fontWeight: 600 }}>{r.best ? bytes(r.best.savings) : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SelectionTray({ sel, setSel }: { sel: string[]; setSel: (f: (s: string[]) => string[]) => void }) {
  const status = useStatus();
  const [info, setInfo] = useState<{ freed: number } | null>(null);
  const [deleting, setDeleting] = useState(false);
  useEffect(() => {
    if (!sel.length) { setInfo(null); return; }
    api.post<{ freed: number }>("/api/selection", { ids: sel }).then(setInfo).catch(() => setInfo(null));
  }, [sel]);
  if (!sel.length) return null;
  return (
    <>
      <Tray figure={bytes(info?.freed ?? 0)} note={t(`freed by deleting ${sel.length} selected`, `frigjøres ved å slette ${sel.length} valgte`)}>
        {!status?.actions_enabled && <span className="small muted">{t("Deletion is off – the next step shows how to switch it on.", "Sletting er av – neste steg viser hvordan du slår det på.")}</span>}
        <button className="btn" onClick={() => setSel(() => [])}>{t("Clear", "Tøm")}</button>
        <button className="btn danger" onClick={() => setDeleting(true)}>{t("Delete selected…", "Slett valgte…")}</button>
      </Tray>
      {deleting && <DeleteDialog ids={sel} onClose={() => setDeleting(false)} onDone={(done) => setSel((s) => s.filter((id) => !done.includes(id)))} />}
    </>
  );
}

/* ------------------------------------------------------------------ movies / series */

export function LibraryPage({ kind }: { kind: "movie" | "series" }) {
  const tick = useRefreshTick();
  const openTitle = useOpenTitle();
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
  const movie = kind === "movie";
  const words: { en: [string, string]; nb: [string, string] } = movie
    ? { en: ["movie", "movies"], nb: ["film", "filmer"] } : { en: ["series", "series"], nb: ["serie", "serier"] };
  const pl = (n: number) => plural(n, words.en, words.nb);
  const stale24 = s?.stale.find((x) => x.months === 24) ?? s?.stale[1];

  const views: { value: string; label: string }[] = [
    { value: "suggested", label: t("Has suggestions", "Har forslag") }, { value: "low_risk", label: t("Safe deletions", "Trygge slettinger") },
    { value: "never", label: t("Never watched", "Aldri sett") },
    ...(s?.stale.map((x) => ({ value: `stale${x.months}`, label: t(`Not watched ${x.months} mo`, `Ikke sett ${x.months} mnd`) })) ?? []),
    ...(movie ? [{ value: "4k", label: "4K" }] : []),
    { value: "requested", label: t("Requested", "Etterspurt") }, { value: "protected", label: t("Protected", "Beskyttet") },
    { value: "all", label: t("All", "Alle") },
  ];

  return (
    <>
      <PageHeader title={movie ? t("Movies", "Filmer") : t("Series", "Serier")} />
      <ErrorNote error={error} />
      {s && (
        <section className="brief">
          <p className="brief-lead">
            {t(`${pl(s.count)} use`, `${pl(s.count)} bruker`)} <b>{bytes(s.bytes)}</b>.{" "}
            {s.suggested.count > 0
              ? <>{t(`${num(s.suggested.count)} of them have suggestions over priority ${s.min_score}, and together`, `${num(s.suggested.count)} av dem har forslag over prioritet ${s.min_score}, og til sammen kan`)} <b>{bytes(s.freed)}</b> {t("can be freed.", "frigjøres.")}</>
              : <>{t(`None have suggestions over priority ${s.min_score}.`, `Ingen har forslag over prioritet ${s.min_score}.`)}</>}
          </p>
          <ul className="brief-points">
            {s.never.count > 0 && <li><button className="linkish" onClick={() => setView("never")}>{pl(s.never.count)}</button> {t(`have never been watched (${bytes(s.never.bytes)}).`, `er aldri sett (${bytes(s.never.bytes)}).`)}</li>}
            {stale24 && stale24.count > 0 && <li><button className="linkish" onClick={() => setView(`stale${stale24.months}`)}>{pl(stale24.count)}</button> {t(`have not been watched for ${stale24.months} months (${bytes(stale24.bytes)}).`, `er ikke sett på ${stale24.months} måneder (${bytes(stale24.bytes)}).`)}</li>}
            {s.low_risk_delete.count > 0 && <li>{t("Safest to start with:", "Tryggest å starte med:")} <button className="linkish" onClick={() => setView("low_risk")}>{plural(s.low_risk_delete.count, ["low-risk deletion", "low-risk deletions"], ["sletting med lav risiko", "slettinger med lav risiko"])}</button>{t(`, which free ${bytes(s.low_risk_delete.freed)}.`, `, som frigjør ${bytes(s.low_risk_delete.freed)}.`)}</li>}
            {movie && s.four_k.count > 0 && <li><button className="linkish" onClick={() => setView("4k")}>{t(`${num(s.four_k.count)} movies in 4K`, `${num(s.four_k.count)} filmer i 4K`)}</button> {t(`use ${bytes(s.four_k.bytes)}.`, `bruker ${bytes(s.four_k.bytes)}.`)} <a href="#/quality">{t("Swap quality", "Bytt kvalitet")}</a></li>}
            {s.protected.count > 0 && <li>{t(`${num(s.protected.count)} are protected and never suggested.`, `${num(s.protected.count)} er beskyttet og vises aldri som forslag.`)}</li>}
          </ul>
          {s.actions.length > 0 && (
            <div className="chips">
              {s.actions.map((a) => <span key={a.kind} className="chip"><b>{kindLabel(a.kind)}</b> {num(a.count)}, {bytes(a.freed)}</span>)}
            </div>
          )}
          {s.top.length > 0 && (
            <>
              <h2 style={{ marginTop: 26 }}>{t("Look at these first", "Bør ses på først")}</h2>
              <div className="top-cards">
                {s.top.map((r) => (
                  <button key={r.key} className="top-card" onClick={() => openTitle(r.key)}>
                    <Poster k={r.key} title={r.name} size="l" />
                    <span className="tc-name">{r.name}</span>
                    <span className="small muted">{r.best?.label}, {bytes(r.best?.savings)}</span>
                    {r.best && <RiskPill risk={r.best.risk} />}
                  </button>
                ))}
              </div>
            </>
          )}
        </section>
      )}

      <div className="toolbar" style={{ marginTop: 32 }}>
        <input type="search" placeholder={movie ? t("Search movies", "Søk i filmer") : t("Search series", "Søk i serier")} value={q} onChange={(e) => setQ(e.target.value)} aria-label={t("Search", "Søk")} />
        <Seg label={t("View", "Utvalg")} value={view} onChange={(v) => { setView(v); setLimit(100); }} options={views} />
      </div>
      {data && <p className="small muted">{pl(data.total)}, {bytes(data.total_bytes)}.</p>}
      {data && <TitleTable rows={data.items} sort={sort} order={order} onSort={onSort} sel={sel} setSel={setSel} />}
      {data && data.items.length === 0 && <div className="empty">{t("Nothing in this view.", "Ingenting i dette utvalget.")}</div>}
      {data && data.total > data.items.length && <p><button className="btn" onClick={() => setLimit(limit + 200)}>{t(`Show more (${num(data.total - data.items.length)} left)`, `Vis flere (${num(data.total - data.items.length)} igjen)`)}</button></p>}
      <SelectionTray sel={sel} setSel={setSel} />
    </>
  );
}

/* ------------------------------------------------------------------ users */

export function UsersPage() {
  const tick = useRefreshTick();
  const { data, error } = useFetch<{ items: Requester[]; seerr?: { ok: boolean; message: string } }>("/api/requesters", [tick]);
  return (
    <>
      <PageHeader title={t("Users", "Brukere")} lede={t("Who requested what in Seerr, and how much of it they actually watched. Open a user for details and cleanup.",
        "Hvem som har bedt om hva i Seerr, og hvor mye av det de faktisk har sett. Åpne en bruker for detaljer og opprydding.")} />
      <ErrorNote error={error} />
      {data && data.items.length === 0 && (
        <div className="empty">{t("No requests found. Connect Seerr under Settings and run a full refresh.", "Ingen forespørsler funnet. Koble til Seerr under Innstillinger og kjør en full oppdatering.")}</div>
      )}
      {data && data.items.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead><tr><th>{t("User", "Bruker")}</th><th className="r">{t("Titles", "Titler")}</th><th className="r">{t("Space", "Plass")}</th>
              <th className="r">{t("Not watched by the user", "Ikke sett av brukeren")}</th><th className="r">{t("Never watched by anyone", "Aldri sett av noen")}</th><th>{t("Last request", "Siste forespørsel")}</th></tr></thead>
            <tbody>
              {data.items.map((r) => {
                const pct = r.titles ? Math.round((r.not_watched_by_requester / r.titles) * 100) : 0;
                return (
                  <tr key={r.name} className="row">
                    <td><a className="title-link" href={`#/users/${encodeURIComponent(r.name)}`}>{r.name}</a></td>
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
  const [view, setView] = useState("unwatched");
  const [sort, setSort] = useState("requested");
  const [order, setOrder] = useState("desc");
  const [sel, setSel] = useState<string[]>([]);
  const { data, error } = useFetch<{ summary: UserSummary; total: number; items: Row[] }>(
    `/api/requesters/${encodeURIComponent(name)}${qs({ view, sort, order })}`, [tick, name]);
  const onSort = (c: string) => { if (sort === c) setOrder(order === "desc" ? "asc" : "desc"); else { setSort(c); setOrder(c === "name" ? "asc" : "desc"); } };
  const s = data?.summary;
  const unwatchedDeletable = useMemo(() => (data?.items ?? []).filter((r) => !r.watched_by_user && r.delete_id && !r.protected).map((r) => r.delete_id!), [data]);
  const pct = s && s.count ? Math.round((s.watched_by_user.count / s.count) * 100) : 0;
  const titles = (n: number) => plural(n, ["title", "titles"], ["tittel", "titler"]);

  return (
    <>
      <p className="small"><a href="#/users">{t("Users", "Brukere")}</a></p>
      <PageHeader title={name} />
      <ErrorNote error={error} />
      {s && (
        <section className="brief">
          <p className="brief-lead">
            {t(`${name} requested`, `${name} har bedt om`)} <b>{titles(s.count)}</b> ({plural(s.movies.count, ["movie", "movies"], ["film", "filmer"])} {t("and", "og")} {plural(s.series.count, ["series", "series"], ["serie", "serier"])}) {t("using", "som bruker")} <b>{bytes(s.bytes)}</b>
            {s.first_request ? t(`, from ${date(s.first_request)} to ${date(s.last_request)}`, `, fra ${date(s.first_request)} til ${date(s.last_request)}`) : ""}.{" "}
            {t(`${name} has watched ${s.watched_by_user.count} of them (${pct} %).`, `${name} har sett ${s.watched_by_user.count} av dem (${pct} %).`)}
          </p>
          <ul className="brief-points">
            <li><button className="linkish" onClick={() => setView("unwatched")}>{titles(s.unwatched_by_user.count)}</button> {t(`not watched by ${name} (${bytes(s.unwatched_by_user.bytes)}).`, `er ikke sett av ${name} (${bytes(s.unwatched_by_user.bytes)}).`)}</li>
            {s.unwatched_older_than_12m.count > 0 && <li><button className="linkish" onClick={() => setView("unwatched_old")}>{num(s.unwatched_older_than_12m.count)}</button> {t(`of them were requested over 12 months ago (${bytes(s.unwatched_older_than_12m.bytes)}).`, `av dem ble etterspurt for over 12 måneder siden (${bytes(s.unwatched_older_than_12m.bytes)}).`)}</li>}
            {s.never_watched.count > 0 && <li><button className="linkish" onClick={() => setView("never")}>{titles(s.never_watched.count)}</button> {t(`not watched by anyone (${bytes(s.never_watched.bytes)}).`, `er ikke sett av noen (${bytes(s.never_watched.bytes)}).`)}</li>}
            {s.unwatched_delete.count > 0 && <li>{t(`Deleting what ${name} has not watched and the app can delete (${titles(s.unwatched_delete.count)}) frees`, `Sletter du det ${name} ikke har sett, og som kan slettes fra appen (${titles(s.unwatched_delete.count)}), frigjøres`)} <b>{bytes(s.unwatched_delete.freed)}</b>.</li>}
          </ul>
        </section>
      )}
      <div className="toolbar" style={{ marginTop: 32 }}>
        <Seg label={t("View", "Utvalg")} value={view} onChange={setView} options={[
          { value: "unwatched", label: t(`Not watched by ${name}`, `Ikke sett av ${name}`) },
          { value: "unwatched_old", label: t("Not watched, over 12 mo", "Ikke sett, over 12 mnd") },
          { value: "never", label: t("Not watched by anyone", "Ikke sett av noen") },
          { value: "watched", label: t("Watched", "Sett") }, { value: "all", label: t("All", "Alle") },
        ]} />
        {unwatchedDeletable.length > 0 && (
          <button className="btn small" onClick={() => setSel((cur) => [...new Set([...cur, ...unwatchedDeletable])])}>{t(`Select all unwatched here (${unwatchedDeletable.length})`, `Velg alle ikke sette her (${unwatchedDeletable.length})`)}</button>
        )}
      </div>
      {data && <TitleTable rows={data.items} sort={sort} order={order} onSort={onSort} sel={sel} setSel={setSel} showRequested />}
      {data && data.items.length === 0 && <div className="empty">{t("Nothing in this view.", "Ingenting i dette utvalget.")}</div>}
      <SelectionTray sel={sel} setSel={setSel} />
    </>
  );
}
