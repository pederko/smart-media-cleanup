import { Requester, Suggestion } from "../api";
import { ago, bytes, date, libColor, num } from "../format";
import { plural, t } from "../i18n";
import { Empty, ErrorNote, HistoryLine, Loading, Poster, RiskPill, ScoreMeter, useFetch, useOpenTitle, useRefreshTick } from "../components/common";
import SetupCard, { SetupStatus } from "../components/SetupCard";

type Lib = { library: string; alloc: number; files: number; kind: string; protected: boolean; index: number };
type Agg = { groups: number; files: number; size: number };
type Overview = {
  capacity: { source: string | null; total?: number; free?: number; used?: number; path?: string;
    pool?: { name: string; size: number; allocated: number; free: number }; root_snapshots?: number | null };
  libraries: Lib[];
  counts: { movies: number; series: number; episodes: number; files: number; protected: number };
  watch_buckets: { code: string; label: string; count: number; bytes: number }[];
  savings: { freed: number; held: number; count: number; min_score: number; by_library?: Record<string, number>;
    recommended: { freed: number; count: number; min_score: number; by_library?: Record<string, number> } };
  areas: {
    delete: { count: number; freed: number };
    quality: { count: number; freed: number; found: number };
    duplicates: { count: number; freed: number };
    downloads: { count: number; freed: number; total: number };
    plex: { available: boolean; not_in_plex: Agg; missing: Agg };
  };
  top_suggestions: Suggestion[];
  history_start: number | null;
  last_analysis: { time: number } | null;
  last_scan: { time: number; files: number; duration: number } | null;
};

export function libHref(kind: string) {
  return kind === "movies" ? "#/movies" : kind === "series" ? "#/series" : kind === "downloads" ? "#/downloads" : "#/files";
}

export default function OverviewPage() {
  const tick = useRefreshTick();
  const { data, error } = useFetch<Overview>("/api/overview", [tick]);
  const setup = useFetch<SetupStatus>("/api/setup", [tick]);
  const req = useFetch<{ items: Requester[] }>("/api/requesters", [tick]);
  const openTitle = useOpenTitle();
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Loading />;
  const showSetup = setup.data && !setup.data.done;

  if (!data.last_scan) {
    return (
      <>
        {showSetup && <SetupCard s={setup.data!} />}
        <Empty>
          <h1>{t("No data yet", "Ingen data ennå")}</h1>
          <p>{t("The first scan runs in the background once the libraries are mounted. Connect Radarr, Sonarr, Plex and Tautulli under Settings for much better suggestions.",
            "Første skanning kjører i bakgrunnen når bibliotekene er montert. Koble til Radarr, Sonarr, Plex og Tautulli under Innstillinger for langt bedre forslag.")}</p>
          <a className="btn primary" href="#/settings">{t("Open settings", "Åpne innstillinger")}</a>
        </Empty>
      </>
    );
  }

  const a = data.areas;
  const cap = data.capacity;
  const used = cap.pool?.allocated ?? cap.used ?? 0;
  const libsTotal = data.libraries.reduce((s, l) => s + l.alloc, 0);
  const other = Math.max(0, used - libsTotal);

  return (
    <>
      {showSetup && <SetupCard s={setup.data!} />}
      <Capacity data={data} other={other} />

      <h2>{t("Where you can free space", "Hvor du kan frigjøre plass")}</h2>
      <div className="areas">
        <Area href="#/suggestions" title={t("Delete titles", "Slett titler")} figure={bytes(a.delete.freed)} dim={!a.delete.count}
          note={a.delete.count ? `${plural(a.delete.count, ["recommended deletion", "recommended deletions"], ["anbefalt sletting", "anbefalte slettinger"])} – ${t("movies, series or seasons nobody watches", "filmer, serier eller sesonger som ingen ser")}` : t("Nothing recommended right now", "Ingenting anbefalt nå")} />
        <Area href="#/quality" title={t("Swap quality", "Bytt kvalitet")} figure={`~${bytes(a.quality.freed)}`} dim={!a.quality.count}
          note={t(`${num(a.quality.count)} large movies and seasons can be swapped for smaller versions`, `${num(a.quality.count)} store filmer og sesonger kan byttes til mindre versjoner`)
            + (a.quality.found ? t(` – ${bytes(a.quality.found)} already found`, ` – ${bytes(a.quality.found)} allerede funnet`) : "")} />
        <Area href="#/duplicates" title={t("Duplicates", "Duplikater")} figure={bytes(a.duplicates.freed)} dim={!a.duplicates.count}
          note={plural(a.duplicates.count, ["group of copies or extra versions", "groups of copies and extra versions"], ["gruppe med kopier eller ekstra versjoner", "grupper med kopier og ekstra versjoner"])} />
        <Area href="#/downloads" title={t("Downloads", "Nedlastinger")} figure={bytes(a.downloads.freed)} dim={!a.downloads.count}
          note={`${plural(a.downloads.count, ["entry", "entries"], ["oppføring", "oppføringer"])} ${t(`can be deleted (of ${bytes(a.downloads.total)} in total)`, `kan slettes (av ${bytes(a.downloads.total)} totalt)`)}`} />
        <Area href="#/plex" title={t("Plex differences", "Plex-avvik")} figure={a.plex.available ? bytes(a.plex.not_in_plex.size) : "–"} dim={!a.plex.available || !a.plex.not_in_plex.groups}
          note={a.plex.available ? t(`${num(a.plex.not_in_plex.groups)} on disk but not in Plex, ${num(a.plex.missing.files)} in Plex but missing on disk`,
            `${num(a.plex.not_in_plex.groups)} på disk men ikke i Plex, ${num(a.plex.missing.files)} i Plex men mangler på disk`) : t("Connect Plex to compare", "Koble til Plex for å sammenligne")} />
        <Area href="#/other" title={t("Other storage", "Annen lagring")} figure={bytes(other)} dim
          note={t("Apps, snapshots and folders outside the libraries – see where to clean up", "Apper, snapshots og mapper utenfor bibliotekene – se hvor du rydder")} />
      </div>

      <div className="figures">
        <Fig v={num(data.counts.movies)} l={t("movies", "filmer")} />
        <Fig v={num(data.counts.series)} l={t(`series, ${num(data.counts.episodes)} episodes`, `serier, ${num(data.counts.episodes)} episoder`)} />
        <Fig v={num(data.watch_buckets[0]?.count)} l={t(`never watched (${bytes(data.watch_buckets[0]?.bytes)})`, `aldri sett (${bytes(data.watch_buckets[0]?.bytes)})`)} />
        <Fig v={num(data.counts.protected)} l={t("protected titles", "beskyttede titler")} />
      </div>

      <div className="grid cols-main">
        <section>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 12 }}>
            <h2>{t("Best suggestions", "Beste forslag")}</h2>
            <a href="#/suggestions" className="small muted">{t(`All ${num(data.savings.count)} suggestions`, `Alle ${num(data.savings.count)} forslag`)}</a>
          </div>
          {data.top_suggestions.length === 0 ? (
            <p className="muted">{t("No recommended suggestions right now.", "Ingen anbefalte forslag nå.")}</p>
          ) : (
            <ol className="rank">
              {data.top_suggestions.map((s) => {
                const name = s.name || s.title_name || s.location;
                return (
                  <li key={s.id}>
                    <ScoreMeter score={s.score} />
                    <div className="with-poster">
                      <Poster k={s.title_key} title={name} />
                      <div style={{ minWidth: 0 }}>
                        {s.title_key ? <button className="t" onClick={() => openTitle(s.title_key!)}>{name}</button> : <span className="t">{name}</span>}
                        <div className="small muted">{s.label} · <HistoryLine h={s.history} /></div>
                      </div>
                    </div>
                    <div style={{ textAlign: "right" }}>
                      <div className="num" style={{ fontWeight: 600 }}>{bytes(s.savings)}</div>
                      <RiskPill risk={s.risk} />
                    </div>
                  </li>
                );
              })}
            </ol>
          )}
        </section>

        <aside className="grid" style={{ alignContent: "start" }}>
          <section className="panel">
            <h2>{t("When was it last watched?", "Når ble det sist sett?")}</h2>
            <Bars rows={data.watch_buckets.map((b) => ({ label: b.label, value: b.bytes, note: plural(b.count, ["title", "titles"], ["tittel", "titler"]) }))} />
            <p className="small muted" style={{ marginBottom: 0 }}>
              {data.history_start
                ? t(`Tautulli history from ${date(data.history_start)}. «Never watched» means no play since then.`, `Tautulli-historikk fra ${date(data.history_start)}. «Aldri sett» betyr ingen avspilling siden da.`)
                : t("No Tautulli history yet.", "Ingen Tautulli-historikk ennå.")}
            </p>
          </section>
          {req.data && req.data.items.length > 0 && (
            <section className="panel">
              <h2>{t("Requested in Seerr", "Etterspurt i Seerr")}</h2>
              <table className="compact">
                <thead><tr><th>{t("User", "Bruker")}</th><th className="r">{t("Titles", "Titler")}</th><th className="r">{t("Not watched by them", "Ikke sett av dem")}</th></tr></thead>
                <tbody>
                  {req.data.items.slice(0, 6).map((r) => (
                    <tr key={r.name}>
                      <td><a href={`#/users/${encodeURIComponent(r.name)}`}>{r.name}</a></td>
                      <td className="r">{r.titles}</td>
                      <td className="r num">{r.not_watched_by_requester} <span className="faint">({bytes(r.not_watched_bytes)})</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="small" style={{ marginBottom: 0 }}><a href="#/users">{t("All users", "Alle brukere")}</a></p>
            </section>
          )}
        </aside>
      </div>

      <p className="small faint section">
        {t(`Analysed ${ago(data.last_analysis?.time)}. Last scan ${ago(data.last_scan.time)}: ${num(data.last_scan.files)} files in ${Math.round(data.last_scan.duration)} s.`,
          `Analysert ${ago(data.last_analysis?.time)}. Siste skanning ${ago(data.last_scan.time)}: ${num(data.last_scan.files)} filer på ${Math.round(data.last_scan.duration)} s.`)}
      </p>
    </>
  );
}

function Area({ href, title, figure, note, dim }: { href: string; title: string; figure: string; note: string; dim?: boolean }) {
  return (
    <a className={`area${dim ? " dim" : ""}`} href={href}>
      <span className="a-title">{title}</span>
      <span className="a-figure">{figure}</span>
      <span className="a-note">{note}</span>
    </a>
  );
}

function Capacity({ data, other }: { data: Overview; other: number }) {
  const cap = data.capacity;
  const pool = cap.pool;
  const total = pool?.size ?? cap.total ?? data.libraries.reduce((s, l) => s + l.alloc, 0);
  const free = pool?.free ?? cap.free ?? 0;
  const rec = data.savings.recommended;
  const byLib = rec.by_library ?? {};
  const pct = (b: number) => `${(b / (total || 1)) * 100}%`;
  return (
    <section className="capacity" aria-label={t("Capacity", "Kapasitet")}>
      <div className="cap-head">
        <div>
          <h1 style={{ marginBottom: 10 }}>{t("Storage", "Lagring")}</h1>
          <div className="cap-figure">{bytes(free)}<span>{t(`free of ${bytes(total)}`, `ledig av ${bytes(total)}`)}</span></div>
        </div>
        <div className="cap-reclaim">
          <div className="cap-figure" style={{ fontSize: 30 }}>{bytes(rec.freed)}</div>
          <div className="muted small">
            {t(`recommended to free (priority ≥ ${rec.min_score}, not high risk)`, `anbefalt å frigjøre (prioritet ≥ ${rec.min_score}, ikke høy risiko)`)}{" "}<br />
            {t(`All ${num(data.savings.count)} suggestions: ${bytes(data.savings.freed)}`, `Alle ${num(data.savings.count)} forslag: ${bytes(data.savings.freed)}`)}
          </div>
        </div>
      </div>
      <div className="cap-bar" role="img" aria-label={t(`${bytes(rec.freed)} recommended to free`, `${bytes(rec.freed)} anbefalt å frigjøre`)}>
        {data.libraries.map((l) => {
          const share = Math.min(l.alloc, byLib[l.library] ?? 0);
          return (
            <a key={l.library} href={libHref(l.kind)} className="cap-seg" style={{ width: pct(l.alloc), background: libColor(l.kind, l.index) }}
              title={`${l.library}: ${bytes(l.alloc)}${share ? t(`, ${bytes(share)} recommended to free`, `, ${bytes(share)} anbefalt å frigjøre`) : ""}`}>
              {share > 0 && <div className="reclaim" style={{ width: `${(share / l.alloc) * 100}%` }} />}
            </a>
          );
        })}
        {other > 0 && <a href="#/other" className="cap-seg" style={{ width: pct(other), background: "var(--lib-other)" }} title={t(`Other: ${bytes(other)}`, `Annet: ${bytes(other)}`)} />}
      </div>
      <div className="cap-legend">
        {data.libraries.map((l) => (
          <a key={l.library} href={libHref(l.kind)} className="cap-key"><i className="k" style={{ background: libColor(l.kind, l.index) }} /><b>{l.library}</b> {bytes(l.alloc)}{l.protected ? <span className="faint"> ({t("protected", "beskyttet")})</span> : null}</a>
        ))}
        {other > 0 && <a href="#/other" className="cap-key"><i className="k" style={{ background: "var(--lib-other)" }} /><b>{t("Other", "Annet")}</b> {bytes(other)}</a>}
        <span><i className="k hatch" />{t("Recommended to free", "Anbefalt å frigjøre")}</span>
        <span className="muted">{t("Free", "Ledig")} {bytes(free)}</span>
      </div>
      <p className="small faint" style={{ marginBottom: 0 }}>
        {pool ? t(`Pool ${pool.name} from TrueNAS.`, `Pool ${pool.name} fra TrueNAS.`)
          : cap.source === "statvfs" ? t(`Capacity measured on the dataset behind ${cap.path}.`, `Kapasitet målt på datasettet bak ${cap.path}.`)
            : t("Capacity unknown – the library folders are not mounted.", "Kapasitet ukjent – bibliotekmappene er ikke montert.")}
        {cap.root_snapshots ? t(` ${cap.root_snapshots} snapshots on the root dataset: deleted space is freed when they expire.`, ` ${cap.root_snapshots} snapshots på rotdatasettet: slettet plass frigjøres først når de utløper.`) : ""}
        {data.savings.held > 0 ? t(` ${bytes(data.savings.held)} is held by hardlinks and not counted.`, ` ${bytes(data.savings.held)} holdes av hardlinker og er ikke regnet med.`) : ""}
      </p>
    </section>
  );
}

function Fig({ v, l }: { v: string; l: string }) {
  return <div className="figure"><div className="v">{v}</div><div className="l">{l}</div></div>;
}

function Bars({ rows }: { rows: { label: string; value: number; note: string }[] }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  if (!rows.length) return <p className="muted small">{t("No data.", "Ingen data.")}</p>;
  return (
    <div className="hbars">
      {rows.map((r) => (
        <div className="hbar" key={r.label}>
          <span>{r.label}</span>
          <span className="track"><i style={{ width: `${(r.value / max) * 100}%`, background: "var(--accent)" }} /></span>
          <span className="v num">{bytes(r.value)} <span className="faint">{r.note}</span></span>
        </div>
      ))}
    </div>
  );
}
