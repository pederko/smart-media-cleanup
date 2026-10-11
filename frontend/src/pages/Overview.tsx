import { Requester, Suggestion } from "../api";
import { ago, bytes, date, fileName, KIND_LABEL, libColor, num } from "../format";
import { Empty, ErrorNote, HistoryLine, RiskPill, ScoreMeter, useFetch, useOpenTitle, useRefreshTick, Poster } from "../components/common";

type Lib = { library: string; alloc: number; files: number; kind: string; protected: boolean };
type Overview = {
  capacity: { source: string | null; total?: number; free?: number; used?: number; path?: string;
    pool?: { name: string; size: number; allocated: number; free: number }; root_snapshots?: number | null };
  libraries: Lib[];
  counts: { movies: number; series: number; episodes: number; files: number; protected: number };
  watch_buckets: { label: string; count: number; bytes: number; movies: number; series: number }[];
  rarely_watched: { count: number; bytes: number };
  savings: { freed: number; held: number; count: number; min_score: number; by_library?: Record<string, number>; by_kind: { kind: string; count: number; freed: number }[]; by_risk: { risk: string; count: number; freed: number }[] };
  largest_movies: { key: string; name: string; year: number; alloc: number; best_resolution: string | null; play_count: number; last_played: number | null }[];
  largest_series: { key: string; name: string; year: number; alloc: number; video_count: number; play_count: number; last_played: number | null }[];
  largest_files: { path: string; size: number; library: string; title_key: string | null; title_name: string | null }[];
  resolution: { res: string; count: number; bytes: number }[];
  top_suggestions: Suggestion[];
  history_start: number | null;
  last_analysis: { time: number } | null;
  last_scan: { time: number; files: number; duration: number } | null;
};

export default function OverviewPage({ go }: { go: (h: string) => void }) {
  const tick = useRefreshTick();
  const { data, error } = useFetch<Overview>("/api/overview", [tick]);
  const openTitle = useOpenTitle();
  const req = useFetch<{ items: Requester[] }>("/api/requesters", [tick]);
  if (error) return <ErrorNote error={error} />;
  if (!data) return <p className="muted">Henter oversikt…</p>;

  if (!data.last_scan) {
    return (
      <Empty>
        <h1>Ingen data ennå</h1>
        <p>Første skanning av bibliotekene går i bakgrunnen. Legg inn adresser og nøkler for Radarr, Sonarr, Plex og Tautulli under Innstillinger, så blir forslagene langt bedre.</p>
        <button className="btn primary" onClick={() => go("innstillinger")}>Åpne innstillinger</button>
      </Empty>
    );
  }

  return (
    <>
      <Capacity data={data} />

      <div className="figures">
        <Fig v={num(data.counts.movies)} l="filmer" />
        <Fig v={num(data.counts.series)} l={`serier, ${num(data.counts.episodes)} episoder`} />
        <Fig v={num(data.watch_buckets[0]?.count)} l={`aldri sett (${bytes(data.watch_buckets[0]?.bytes)})`} />
        <Fig v={num(data.rarely_watched.count)} l="sett bare 1–2 ganger" />
        <Fig v={num(data.counts.protected)} l="beskyttede titler" />
      </div>

      <div className="grid cols-main">
        <section>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 12 }}>
            <h2>Beste oppryddingsforslag</h2>
            <a href="#/forslag" className="small muted">Alle {num(data.savings.count)} forslag</a>
          </div>
          {data.top_suggestions.length === 0 ? (
            <p className="muted">Ingen forslag over prioritet {data.savings.min_score}. Senk terskelen under Innstillinger for å se flere.</p>
          ) : (
            <ol className="rank">
              {data.top_suggestions.map((s) => (
                <li key={s.id}>
                  <ScoreMeter score={s.score} />
                  <div className="with-poster">
                    <Poster k={s.title_key} title={s.label} />
                    <div style={{ minWidth: 0 }}>
                      {s.title_key ? <button className="t" onClick={() => openTitle(s.title_key!)}>{s.label}</button> : <span className="t">{s.label}</span>}
                      <div className="small muted"><span>{s.action}</span>, <HistoryLine h={s.history} /></div>
                    </div>
                  </div>
                  <div style={{ textAlign: "right" }}>
                    <div className="num" style={{ fontWeight: 600 }}>{bytes(s.savings)}</div>
                    <RiskPill risk={s.risk} />
                  </div>
                </li>
              ))}
            </ol>
          )}
        </section>

        <aside className="grid" style={{ alignContent: "start" }}>
          <section className="panel">
            <h2>Når ble innholdet sist sett?</h2>
            <Bars rows={data.watch_buckets.map((b) => ({ label: b.label, value: b.bytes, note: `${num(b.count)} titler` }))} color="var(--accent)" />
            <p className="small muted" style={{ marginBottom: 0 }}>
              {data.history_start ? `Tautulli-historikk fra ${date(data.history_start)}. «Aldri sett» betyr ingen avspilling siden da.` : "Ingen Tautulli-historikk ennå."}
            </p>
          </section>
          {req.data && req.data.items.length > 0 && (
            <section className="panel">
              <h2>Etterspurt i Seerr</h2>
              <table className="compact">
                <thead><tr><th>Bruker</th><th className="r">Titler</th><th className="r">Plass</th><th className="r">Ikke sett av dem</th></tr></thead>
                <tbody>
                  {req.data.items.slice(0, 10).map((r) => (
                    <tr key={r.name}>
                      <td><a href={`#/forslag?etterspurt=${encodeURIComponent(r.name)}`}>{r.name}</a></td>
                      <td className="r">{r.titles}</td>
                      <td className="r num">{bytes(r.bytes)}</td>
                      <td className="r num">{r.not_watched_by_requester} <span className="faint">({bytes(r.not_watched_bytes)})</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="small muted" style={{ marginBottom: 0 }}>«Ikke sett av dem» betyr at den som ba om tittelen ikke har spilt den av i Tautulli-historikken.</p>
            </section>
          )}
          <section className="panel">
            <h2>Forslag etter type</h2>
            <Bars rows={data.savings.by_kind.sort((a, b) => b.freed - a.freed).map((k) => ({ label: KIND_LABEL[k.kind] ?? k.kind, value: k.freed, note: `${k.count} stk` }))} color="var(--lib-film)" />
          </section>
          <section className="panel">
            <h2>Filmer etter oppløsning</h2>
            <Bars rows={data.resolution.map((r) => ({ label: r.res, value: r.bytes, note: `${num(r.count)} filmer` }))} color="var(--lib-tv)" />
          </section>
        </aside>
      </div>

      <div className="grid cols-3 section">
        <section>
          <h2>Største filmer</h2>
          <Top rows={data.largest_movies.map((m) => ({ key: m.key, name: m.name, sub: `${m.best_resolution ?? "?"}, ${m.play_count ? `sett ${ago(m.last_played)}` : "aldri sett"}`, size: m.alloc }))} onOpen={openTitle} />
        </section>
        <section>
          <h2>Største serier</h2>
          <Top rows={data.largest_series.map((m) => ({ key: m.key, name: m.name, sub: `${m.video_count} episodefiler, ${m.play_count ? `sett ${ago(m.last_played)}` : "aldri sett"}`, size: m.alloc }))} onOpen={openTitle} />
        </section>
        <section>
          <h2>Største filer</h2>
          <Top rows={data.largest_files.map((f) => ({ key: f.title_key, name: fileName(f.path), sub: f.title_name ?? f.library, size: f.size, poster: false }))} onOpen={openTitle} />
        </section>
      </div>

      <p className="small faint section">
        Analysert {ago(data.last_analysis?.time)}. Siste skanning {ago(data.last_scan.time)}: {num(data.last_scan.files)} filer på {Math.round(data.last_scan.duration)} s.
      </p>
    </>
  );
}

function Capacity({ data }: { data: Overview }) {
  const cap = data.capacity;
  const pool = cap.pool;
  const total = pool?.size ?? cap.total ?? data.libraries.reduce((s, l) => s + l.alloc, 0);
  const used = pool?.allocated ?? cap.used ?? data.libraries.reduce((s, l) => s + l.alloc, 0);
  const free = pool?.free ?? cap.free ?? Math.max(0, total - used);
  const libsTotal = data.libraries.reduce((s, l) => s + l.alloc, 0);
  const other = Math.max(0, used - libsTotal);
  const reclaimTotal = data.savings.freed;
  const byLib = data.savings.by_library ?? {};
  const pct = (b: number) => `${(b / (total || 1)) * 100}%`;
  return (
    <section className="capacity" aria-label="Kapasitet">
      <div className="cap-head">
        <div>
          <h1 style={{ marginBottom: 10 }}>Lagring</h1>
          <div className="cap-figure">{bytes(free)}<span>ledig av {bytes(total)}</span></div>
        </div>
        <div className="cap-reclaim">
          <div className="cap-figure" style={{ fontSize: 30 }}>{bytes(reclaimTotal)}</div>
          <div className="muted small">kan frigjøres med forslagene over prioritet {data.savings.min_score},<br />uten dobbelttelling</div>
        </div>
      </div>
      <div className="cap-bar" role="img" aria-label={`Brukt ${bytes(used)} av ${bytes(total)}, ${bytes(reclaimTotal)} kan frigjøres`}>
        {data.libraries.map((l, i) => {
          const share = Math.min(l.alloc, byLib[l.library] ?? 0);
          return (
            <div key={l.library} className="cap-seg" style={{ width: pct(l.alloc), background: libColor(l.library, i) }} title={`${l.library}: ${bytes(l.alloc)}${share ? `, ${bytes(share)} kan frigjøres` : ""}`}>
              {share > 0 && <div className="reclaim" style={{ width: `${(share / l.alloc) * 100}%` }} />}
            </div>
          );
        })}
        {other > 0 && <div className="cap-seg" style={{ width: pct(other), background: "var(--lib-other)" }} title={`Annet: ${bytes(other)}`} />}
      </div>
      <div className="cap-legend">
        {data.libraries.map((l, i) => (
          <span key={l.library}><i className="k" style={{ background: libColor(l.library, i) }} /><b>{l.library}</b> {bytes(l.alloc)}{l.protected ? <span className="faint"> (beskyttet)</span> : null}</span>
        ))}
        {other > 0 && <span><i className="k" style={{ background: "var(--lib-other)" }} /><b>Annet</b> {bytes(other)}</span>}
        <span><i className="k hatch" />Kan frigjøres {bytes(reclaimTotal)}</span>
        <span className="muted">Ledig {bytes(free)}</span>
      </div>
      <p className="small faint" style={{ marginBottom: 0 }}>
        {pool ? `Pool ${pool.name} fra TrueNAS.` : cap.source === "statvfs" ? `Kapasitet målt på datasettet bak ${cap.path}.` : "Kapasitet ukjent – bibliotekmappene er ikke montert."}
        {cap.root_snapshots ? ` ${cap.root_snapshots} snapshots på rotdatasettet: slettet plass frigjøres først når de utløper.` : ""}
        {data.savings.held > 0 ? ` ${bytes(data.savings.held)} holdes av hardlinker og er ikke regnet med.` : ""}
      </p>
    </section>
  );
}

function Fig({ v, l }: { v: string; l: string }) {
  return <div className="figure"><div className="v">{v}</div><div className="l">{l}</div></div>;
}

function Bars({ rows, color }: { rows: { label: string; value: number; note: string }[]; color: string }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  if (!rows.length) return <p className="muted small">Ingen data.</p>;
  return (
    <div className="hbars">
      {rows.map((r) => (
        <div className="hbar" key={r.label}>
          <span>{r.label}</span>
          <span className="track"><i style={{ width: `${(r.value / max) * 100}%`, background: color }} /></span>
          <span className="v num">{bytes(r.value)} <span className="faint">{r.note}</span></span>
        </div>
      ))}
    </div>
  );
}

function Top({ rows, onOpen }: { rows: { key: string | null; name: string; sub: string; size: number; poster?: boolean }[]; onOpen: (k: string) => void }) {
  return (
    <ol className="rank">
      {rows.map((r, i) => (
        <li key={i} style={{ gridTemplateColumns: "1fr auto" }}>
          <div className="with-poster">
            {r.poster !== false && <Poster k={r.key} title={r.name} />}
            <div style={{ minWidth: 0 }}>
              {r.key ? <button className="t" onClick={() => onOpen(r.key!)} style={{ wordBreak: "break-word" }}>{r.name}</button> : <span className="t">{r.name}</span>}
              <div className="small muted">{r.sub}</div>
            </div>
          </div>
          <span className="num">{bytes(r.size)}</span>
        </li>
      ))}
    </ol>
  );
}
