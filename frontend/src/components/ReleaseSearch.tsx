import { Fragment, useEffect, useState } from "react";
import { api } from "../api";
import { bytes, num } from "../format";
import { t } from "../i18n";
import { useFetch, useStatus } from "./common";
import { swapsChanged } from "./Swaps";

type Release = { title: string; size: number; quality: string | null; resolution: number | null; indexer: string | null;
  protocol: string | null; seeders: number | null; age_days: number | null; languages: string[]; score: number;
  reasons: string[]; warnings: string[]; savings: number; recommended: boolean; info_url: string | null; guid: string; indexer_id: number };
type Result = { service: string; current_size: number; episodes: number; target: number; total: number; episode_releases: number;
  smaller: number; releases: Release[]; searched: number; cached: boolean };

/** What happens after the swap: keep as before, unmonitor, or change the quality profile. */
export function AfterSwapSelect({ service, value, onChange, season }: { service: string | null; value: string; onChange: (v: string) => void; season?: boolean }) {
  const profiles = useFetch<{ items: { id: number; name: string }[] }>(service ? `/api/quality-profiles/${service}` : null, [service]);
  const svc = service === "sonarr" ? "Sonarr" : service === "radarr" ? "Radarr" : "Radarr/Sonarr";
  return (
    <label className="small">{t("After the swap:", "Etter byttet:")}{" "}
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="none">{t(`Leave ${svc} as before`, `La ${svc} være som før`)}</option>
        <option value="unmonitor">{season ? t("Unmonitor the season, so it is not upgraded back", "Avovervåk sesongen, så den ikke oppgraderes tilbake") : t("Unmonitor, so it is not upgraded back", "Avovervåk, så den ikke oppgraderes tilbake")}</option>
        {profiles.data?.items.map((p) => <option key={p.id} value={`profile:${p.id}`}>{t(`Change the quality profile to «${p.name}»`, `Bytt kvalitetsprofil til «${p.name}»`)}</option>)}
      </select>
    </label>
  );
}

/** Confirmation for «download and swap». Nothing happens until the button is pressed. */
function SwapConfirm({ r, titleKey, season, service, current, onDone }: { r: Release; titleKey: string; season?: number;
  service: string; current: number; onDone: (msg: string | null) => void }) {
  const svc = service === "sonarr" ? "Sonarr" : "Radarr";
  const [after, setAfter] = useState("none");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const go = async () => {
    setBusy(true); setErr(null);
    try {
      await api.post("/api/swaps", { key: titleKey, guid: r.guid, indexer_id: r.indexer_id, season: season ?? null, after_swap: after });
      swapsChanged();
      onDone(t(`Started. ${svc} is downloading «${r.title}». Follow it under «Swaps» below or under Activity.`, `Startet. ${svc} laster ned «${r.title}». Følg med under «Bytter» lenger ned eller under Aktivitet.`));
    } catch (e) { setErr(String((e as Error).message)); } finally { setBusy(false); }
  };
  return (
    <div className="notice" style={{ margin: "8px 0" }}>
      <p style={{ marginTop: 0 }}><b>{season != null ? t(`Download and swap season ${season}`, `Last ned og bytt sesong ${season}`) : t("Download and swap", "Last ned og bytt")}</b></p>
      <ol className="small" style={{ paddingLeft: 18 }}>
        <li>{t(`${svc} downloads «${r.title}» (${bytes(r.size)}). The current file (${bytes(current)}) stays in the meantime.`, `${svc} laster ned «${r.title}» (${bytes(r.size)}). Den nåværende filen (${bytes(current)}) blir liggende i mellomtiden.`)}</li>
        <li>{t(`When the download is finished, the app checks that it can be imported. Only then is the old file deleted through ${svc} and the new one imported.`, `Når nedlastingen er ferdig, sjekker appen at den kan importeres. Bare da slettes den gamle via ${svc}, og den nye importeres.`)}</li>
        <li>{t("If anything fails, the swap stops and the old file is untouched.", "Feiler noe, stopper byttet og den gamle filen er urørt.")}</li>
      </ol>
      <AfterSwapSelect service={service} value={after} onChange={setAfter} season={season != null} />
      {after === "none" && <p className="small muted" style={{ margin: "6px 0 0" }}>{t(`With «as before», ${svc} may later fetch a larger version again if its quality profile wants one.`, `Med «som før» kan ${svc} senere hente en større versjon igjen hvis kvalitetsprofilen ønsker det.`)}</p>}
      {err && <div className="notice err" style={{ marginTop: 8 }}>{err}</div>}
      <p style={{ marginBottom: 0 }}>
        <button className="btn primary small" disabled={busy} onClick={go}>{busy ? t("Starting…", "Starter…") : t(`Confirm: download and swap (saves ${bytes(r.savings)})`, `Bekreft: last ned og bytt (sparer ${bytes(r.savings)})`)}</button>{" "}
        <button className="btn small" onClick={() => onDone(null)}>{t("Cancel", "Avbryt")}</button>
      </p>
    </div>
  );
}

/** Search for smaller versions through the interactive search of Radarr/Sonarr, with an optional swap. */
export default function ReleaseSearch({ titleKey, season, label, autoStart }: { titleKey: string; season?: number; label?: string; autoStart?: boolean }) {
  const status = useStatus();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [res, setRes] = useState<Result | null>(null);
  const [all, setAll] = useState(false);
  const [pick, setPick] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const canSwap = !!status?.actions_enabled;
  const run = async (refresh = false) => {
    setOpen(true); setBusy(true); setError(null);
    try {
      const q = new URLSearchParams();
      if (season != null) q.set("season", String(season));
      if (refresh) q.set("refresh", "true");
      setRes(await api.get<Result>(`/api/releases/${encodeURIComponent(titleKey)}?${q}`));
    } catch (e) { setError(String((e as Error).message)); } finally { setBusy(false); }
  };
  useEffect(() => { if (autoStart) run(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const svc = res?.service === "sonarr" ? "Sonarr" : "Radarr";
  const shown = res ? (all ? res.releases : res.releases.slice(0, 8)) : [];

  if (!open) return <button className="btn small" onClick={() => run()}>{label ?? t("Find a smaller version", "Finn mindre versjon")}</button>;
  return (
    <div className="panel release-box">
      <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "baseline", flexWrap: "wrap" }}>
        <h3 style={{ margin: 0 }}>{season != null ? t(`Season ${season}`, `Sesong ${season}`) : t("Found at the indexers", "Funnet hos indekserne")}</h3>
        <span className="small">
          {res && !busy && <button className="linkish small" onClick={() => run(true)}>{t("Search again", "Søk på nytt")}</button>}{" "}
          <button className="linkish small" onClick={() => setOpen(false)}>{t("Hide", "Skjul")}</button>
        </span>
      </div>
      {busy && <p className="muted small">{t(`Searching the indexers through ${res ? svc : "Radarr/Sonarr"}… This can take up to a minute.`, `Søker i indekserne via ${res ? svc : "Radarr/Sonarr"}… Dette kan ta opptil et minutt.`)}</p>}
      {error && <div className="notice err">{error}</div>}
      {res && !busy && (
        <>
          <p className="small muted">
            {t(`Today: ${bytes(res.current_size)}${res.service === "sonarr" ? ` (${num(res.episodes)} episodes)` : ""}. ${svc} found ${num(res.total)} releases${res.service === "sonarr" ? " as season packs" : ""}, of which ${num(res.smaller)} are at least 15 % smaller.`,
              `I dag: ${bytes(res.current_size)}${res.service === "sonarr" ? ` (${num(res.episodes)} episoder)` : ""}. ${svc} fant ${num(res.total)} utgivelser${res.service === "sonarr" ? " som sesongpakker" : ""}, hvorav ${num(res.smaller)} er minst 15 % mindre.`)}
            {res.episode_releases > 0 && t(` ${num(res.episode_releases)} single episodes are left out.`, ` ${num(res.episode_releases)} enkeltepisoder er ikke tatt med.`)}
            {res.cached && t(" (From the last 30 minutes.)", " (Fra de siste 30 minuttene.)")}
          </p>
          {res.releases.length === 0 ? <p className="muted">{t("No smaller versions at the indexers right now.", "Ingen mindre versjoner funnet hos indekserne nå.")}</p> : (
            <div className="table-wrap">
              <table className="compact">
                <thead><tr><th>{t("Release", "Utgivelse")}</th><th>{t("Quality", "Kvalitet")}</th><th className="r">{t("Size", "Størrelse")}</th><th className="r">{t("Saves", "Sparer")}</th><th>{t("Availability", "Tilgjengelighet")}</th><th /></tr></thead>
                <tbody>
                  {shown.map((r) => (
                    <Fragment key={r.guid + r.indexer_id}>
                      <tr className={r.recommended ? "rec" : ""}>
                        <td style={{ maxWidth: 380 }}>
                          {r.recommended && <span className="pill risk-low" style={{ marginRight: 6 }}>{t("Recommended", "Anbefalt")}</span>}
                          <span style={{ wordBreak: "break-word" }}>{r.title}</span>
                          <div className="small muted">{r.reasons.join(", ")}{r.languages.length ? `, ${r.languages.join("/")}` : ""}</div>
                          {r.warnings.length > 0 && <div className="small" style={{ color: "var(--risk-medium)" }}>{r.warnings.join(". ")}</div>}
                        </td>
                        <td className="small">{r.quality}</td>
                        <td className="r num">{bytes(r.size)}</td>
                        <td className="r num" style={{ fontWeight: 600 }}>{bytes(r.savings)}</td>
                        <td className="small muted">{r.protocol === "torrent" ? t(`${r.seeders ?? 0} seeders`, `${r.seeders ?? 0} delere`) : r.protocol === "usenet" ? "Usenet" : ""}{r.indexer ? `, ${r.indexer}` : ""}{r.age_days != null ? t(`, ${num(r.age_days)} d`, `, ${num(r.age_days)} d`) : ""}</td>
                        <td className="r">
                          <button className="btn small" disabled={!canSwap} title={canSwap ? "" : t("Switch on deletion through Radarr/Sonarr under Settings → Deletion", "Slå på sletting via Radarr/Sonarr under Innstillinger → Sletting")}
                            onClick={() => { setPick(r.guid + r.indexer_id); setDone(null); }}>{t("Swap", "Bytt")}</button>
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
          {res.releases.length > 0 && !canSwap && <p className="small muted">{t("«Swap» requires deletion through Radarr/Sonarr to be switched on under Settings → Deletion.", "«Bytt» krever at sletting via Radarr/Sonarr er slått på under Innstillinger → Sletting.")}</p>}
          {res.releases.length > 8 && <p className="small"><button className="linkish" onClick={() => setAll(!all)}>{all ? t("Show fewer", "Vis færre") : t(`Show all ${res.releases.length}`, `Vis alle ${res.releases.length}`)}</button></p>}
          <p className="small muted" style={{ marginBottom: 0 }}>
            {t(`«Recommended» weighs the saving, 1080p, size close to the target, seeders and any rejections from ${svc}. The rejection «not an upgrade» is expected when going down in size and is not shown. «Swap» downloads first and swaps afterwards: the large file is not deleted until the new one is downloaded and can be imported.`,
              `«Anbefalt» veier gevinst, 1080p, størrelse nær målet, antall delere og eventuelle avvisninger fra ${svc}. Avvisningen «ikke en oppgradering» er forventet når man går ned i størrelse og vises ikke. «Bytt» laster ned først og bytter etterpå: den store filen slettes ikke før den nye er ferdig nedlastet og kan importeres.`)}
          </p>
        </>
      )}
    </div>
  );
}
