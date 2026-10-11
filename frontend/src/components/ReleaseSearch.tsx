import { Fragment, useState } from "react";
import { api } from "../api";
import { bytes, num } from "../format";
import { useFetch } from "./common";
import { swapsChanged } from "./Swaps";

type Release = { title: string; size: number; quality: string | null; resolution: number | null; indexer: string | null;
  protocol: string | null; seeders: number | null; age_days: number | null; languages: string[]; score: number;
  reasons: string[]; warnings: string[]; savings: number; recommended: boolean; info_url: string | null; guid: string; indexer_id: number };
type Result = { service: string; current_size: number; episodes: number; target: number; total: number; episode_releases: number;
  smaller: number; releases: Release[]; searched: number; cached: boolean };

/** Bekreftelse for «last ned og bytt». Ingenting skjer før knappen trykkes. */
function SwapConfirm({ r, titleKey, season, service, current, onDone }: { r: Release; titleKey: string; season?: number;
  service: string; current: number; onDone: (msg: string | null) => void }) {
  const svc = service === "sonarr" ? "Sonarr" : "Radarr";
  const [after, setAfter] = useState("none");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const profiles = useFetch<{ items: { id: number; name: string }[] }>(`/api/quality-profiles/${service}`, [service]);
  const go = async () => {
    setBusy(true); setErr(null);
    try {
      await api.post("/api/swaps", { key: titleKey, guid: r.guid, indexer_id: r.indexer_id, season: season ?? null, after_swap: after });
      swapsChanged();
      onDone(`Startet. ${svc} laster ned «${r.title}». Følg med under «Bytter» lenger ned eller på Jobber-siden.`);
    } catch (e) { setErr(String((e as Error).message)); } finally { setBusy(false); }
  };
  return (
    <div className="notice" style={{ margin: "8px 0" }}>
      <p style={{ marginTop: 0 }}><b>Last ned og bytt{season != null ? ` sesong ${season}` : ""}</b></p>
      <ol className="small" style={{ paddingLeft: 18 }}>
        <li>{svc} laster ned «{r.title}» ({bytes(r.size)}). Den nåværende filen ({bytes(current)}) blir liggende i mellomtiden.</li>
        <li>Når nedlastingen er ferdig, sjekker appen at filen kan importeres. Bare da slettes den gamle via {svc}, og den nye importeres.</li>
        <li>Feiler noe, stopper byttet og den gamle filen er urørt.</li>
      </ol>
      <label className="small">Etter byttet:{" "}
        <select value={after} onChange={(e) => setAfter(e.target.value)}>
          <option value="none">La {svc} være som før</option>
          <option value="unmonitor">Avovervåk{season != null ? " sesongen" : ""}, så den ikke oppgraderes tilbake</option>
          {profiles.data?.items.map((p) => <option key={p.id} value={`profile:${p.id}`}>Bytt kvalitetsprofil til «{p.name}»</option>)}
        </select>
      </label>
      {after === "none" && <p className="small muted" style={{ margin: "6px 0 0" }}>Med «som før» kan {svc} senere hente en større versjon igjen hvis kvalitetsprofilen ønsker det.</p>}
      {err && <div className="notice err" style={{ marginTop: 8 }}>{err}</div>}
      <p style={{ marginBottom: 0 }}>
        <button className="btn primary small" disabled={busy} onClick={go}>{busy ? "Starter…" : `Bekreft: last ned og bytt (sparer ${bytes(r.savings)})`}</button>{" "}
        <button className="btn small" onClick={() => onDone(null)}>Avbryt</button>
      </p>
    </div>
  );
}

/** Søk etter mindre versjoner via Radarr/Sonarr sin interaktive søk, med valgfritt bytte. */
export default function ReleaseSearch({ titleKey, season, label }: { titleKey: string; season?: number; label?: string }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [res, setRes] = useState<Result | null>(null);
  const [all, setAll] = useState(false);
  const [pick, setPick] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const status = useFetch<{ actions_enabled: boolean }>("/api/status", []);
  const canSwap = !!status.data?.actions_enabled;
  const run = async (refresh = false) => {
    setOpen(true); setBusy(true); setError(null);
    try {
      const q = new URLSearchParams();
      if (season != null) q.set("season", String(season));
      if (refresh) q.set("refresh", "true");
      setRes(await api.get<Result>(`/api/releases/${encodeURIComponent(titleKey)}?${q}`));
    } catch (e) { setError(String((e as Error).message)); } finally { setBusy(false); }
  };
  const svc = res?.service === "sonarr" ? "Sonarr" : "Radarr";
  const shown = res ? (all ? res.releases : res.releases.slice(0, 8)) : [];

  if (!open) return <button className="btn small" onClick={() => run()}>{label ?? "Finn mindre versjon"}</button>;
  return (
    <div className="panel release-box">
      <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "baseline", flexWrap: "wrap" }}>
        <h3 style={{ margin: 0 }}>{season != null ? `Sesong ${season}` : "Funnet hos indekserne"}</h3>
        <span className="small">
          {res && !busy && <button className="linkish small" onClick={() => run(true)}>Søk på nytt</button>}{" "}
          <button className="linkish small" onClick={() => setOpen(false)}>Skjul</button>
        </span>
      </div>
      {busy && <p className="muted small">Søker i indekserne via {res ? svc : "Radarr/Sonarr"}… Dette kan ta opptil et minutt.</p>}
      {error && <div className="notice err">{error}</div>}
      {res && !busy && (
        <>
          <p className="small muted">
            I dag: {bytes(res.current_size)}{res.service === "sonarr" ? ` (${num(res.episodes)} episoder)` : ""}. {svc} fant {num(res.total)} utgivelser
            {res.service === "sonarr" ? " som sesongpakker" : ""}, hvorav {num(res.smaller)} er minst 15 % mindre.
            {res.episode_releases > 0 && ` ${num(res.episode_releases)} enkeltepisoder er ikke tatt med.`}
            {res.cached && " (Fra de siste 30 minuttene.)"}
          </p>
          {res.releases.length === 0 ? <p className="muted">Ingen mindre versjoner funnet hos indekserne nå.</p> : (
            <div className="table-wrap">
              <table className="compact">
                <thead><tr><th>Utgivelse</th><th>Kvalitet</th><th className="r">Størrelse</th><th className="r">Sparer</th><th>Tilgjengelighet</th><th /></tr></thead>
                <tbody>
                  {shown.map((r) => (
                    <Fragment key={r.guid + r.indexer_id}>
                    <tr className={r.recommended ? "rec" : ""}>
                      <td style={{ maxWidth: 380 }}>
                        {r.recommended && <span className="pill risk-lav" style={{ marginRight: 6 }}>Anbefalt</span>}
                        <span style={{ wordBreak: "break-word" }}>{r.title}</span>
                        <div className="small muted">{r.reasons.join(", ")}{r.languages.length ? `, ${r.languages.join("/")}` : ""}</div>
                        {r.warnings.length > 0 && <div className="small" style={{ color: "var(--risk-middels)" }}>{r.warnings.join(". ")}</div>}
                      </td>
                      <td className="small">{r.quality}</td>
                      <td className="r num">{bytes(r.size)}</td>
                      <td className="r num" style={{ fontWeight: 600 }}>{bytes(r.savings)}</td>
                      <td className="small muted">{r.protocol === "torrent" ? `${r.seeders ?? 0} delere` : r.protocol === "usenet" ? "Usenet" : ""}{r.indexer ? `, ${r.indexer}` : ""}{r.age_days != null ? `, ${num(r.age_days)} d` : ""}</td>
                      <td className="r">
                        <button className="btn small" disabled={!canSwap} title={canSwap ? "" : "Slå på sletting via Radarr/Sonarr under Innstillinger → Sletting"}
                          onClick={() => { setPick(r.guid + r.indexer_id); setDone(null); }}>Bytt</button>
                      </td>
                    </tr>
                    {pick === r.guid + r.indexer_id && (
                      <tr className="detail"><td colSpan={6}>
                        <SwapConfirm r={r} titleKey={titleKey} season={season} service={res.service} current={res.current_size}
                          onDone={(m) => { setPick(null); setDone(m); }} />
                      </td></tr>
                    )}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {done && <div className="notice ok">{done}</div>}
          {res.releases.length > 0 && !canSwap && <p className="small muted">«Bytt» krever at sletting via Radarr/Sonarr er slått på under Innstillinger → Sletting.</p>}
          {res.releases.length > 8 && <p className="small"><button className="linkish" onClick={() => setAll(!all)}>{all ? "Vis færre" : `Vis alle ${res.releases.length}`}</button></p>}
          <p className="small muted" style={{ marginBottom: 0 }}>
            «Anbefalt» veier gevinst, 1080p, størrelse nær målet, antall delere og eventuelle avvisninger fra {svc}. Avvisningen «ikke en oppgradering» er forventet når man går ned i størrelse og vises ikke.
            «Bytt» laster ned først og bytter etterpå: den store filen slettes ikke før den nye er ferdig nedlastet og kan importeres.
          </p>
        </>
      )}
    </div>
  );
}
