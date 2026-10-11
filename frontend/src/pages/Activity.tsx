import { Fragment, useEffect, useState } from "react";
import { api, Job } from "../api";
import { ago, bytes, num } from "../format";
import { locale, t } from "../i18n";
import { ErrorNote, PageHeader, statusLabel, StatusDot, useFetch, useRefreshTick, useStatus } from "../components/common";
import SwapList from "../components/Swaps";

/** Activity: background jobs, swaps in progress and the log of everything the app has deleted. */
export default function ActivityPage({ tab }: { tab: string }) {
  const status = useStatus();
  const tabs = [
    { id: "jobs", label: t("Jobs", "Jobber") },
    { id: "swaps", label: t("Swaps", "Bytter"), count: status?.active_swaps || 0 },
    { id: "log", label: t("Deletion log", "Slettelogg") },
  ];
  return (
    <>
      <PageHeader title={t("Activity", "Aktivitet")} />
      <nav className="tabs" aria-label={t("Activity", "Aktivitet")}>
        {tabs.map((x) => (
          <a key={x.id} href={`#/activity/${x.id}`} aria-current={tab === x.id ? "page" : undefined}>
            {x.label}{x.count ? <span className="count">{x.count}</span> : null}
          </a>
        ))}
      </nav>
      {tab === "swaps" ? <SwapsTab /> : tab === "log" ? <LogTab /> : <JobsTab />}
    </>
  );
}

function JobsTab() {
  const tick = useRefreshTick();
  const status = useStatus();
  const [poll, setPoll] = useState(0);
  const { data, error } = useFetch<{ items: Job[]; kinds: Record<string, string> }>("/api/jobs", [tick, poll]);
  const [open, setOpen] = useState<number | null>(null);
  useEffect(() => { const iv = setInterval(() => setPoll((p) => p + 1), 3000); return () => clearInterval(iv); }, []);
  const start = async (k: string) => { await api.post(`/api/jobs/${k}`); setPoll((p) => p + 1); };
  const ls = status?.last_scan;
  const jobStatus = (s: string) => ({ done: t("Done", "Ferdig"), failed: t("Failed", "Feilet"), running: t("Running", "Kjører"),
    queued: t("Queued", "I kø"), aborted: t("Aborted", "Avbrutt") } as Record<string, string>)[s] ?? s;
  return (
    <>
      <p className="lede">{t("Scanning and syncing run automatically in the background. Only one job runs at a time to spare the pool.",
        "Skanning og synkronisering går automatisk i bakgrunnen. Bare én jobb kjører om gangen for å skåne poolen.")}</p>
      {ls?.missing?.length ? <div className="notice err">{t(`The folders for ${ls.missing.join(", ")} were not found in the container. Check the volumes in the app's compose file.`, `Fant ikke mappene for ${ls.missing.join(", ")} i containeren. Sjekk volumene i appens compose-fil.`)}</div> : null}
      <div className="figures">
        <div className="figure"><div className="v">{ago(status?.last_sync)}</div><div className="l">{t("last sync with the services", "siste synk med tjenestene")}</div></div>
        <div className="figure"><div className="v">{ago(ls?.time)}</div><div className="l">{ls ? t(`${ls.full ? "full" : "incremental"} scan, ${num(ls.files)} files, ${bytes(ls.bytes)}, ${Math.round(ls.duration)} s`, `${ls.full ? "full" : "inkrementell"} skanning, ${num(ls.files)} filer, ${bytes(ls.bytes)}, ${Math.round(ls.duration)} s`) : t("last scan", "siste skanning")}</div></div>
        <div className="figure"><div className="v">{ago(status?.last_analysis?.time)}</div><div className="l">{t("last analysis", "siste analyse")}</div></div>
      </div>
      <div className="toolbar">
        <button className="btn primary" onClick={() => start("refresh")}>{t("Run full refresh", "Kjør full oppdatering")}</button>
        <button className="btn" onClick={() => start("sync")}>{t("Sync services", "Synk tjenester")}</button>
        <button className="btn" onClick={() => start("scan")}>{t("Scan changes", "Skann endringer")}</button>
        <button className="btn" onClick={() => start("scan_full")}>{t("Full scan", "Full skanning")}</button>
        <button className="btn" onClick={() => start("analyze")}>{t("Analysis", "Analyse")}</button>
      </div>
      <ErrorNote error={error} />
      <div className="table-wrap">
        <table>
          <thead><tr><th>{t("Job", "Jobb")}</th><th>{t("Status", "Status")}</th><th>{t("Progress", "Fremdrift")}</th><th>{t("Started", "Startet")}</th><th>{t("Duration", "Varighet")}</th></tr></thead>
          <tbody>
            {data?.items.map((j) => (
              <Fragment key={j.id}>
                <tr className="row" onClick={() => setOpen(open === j.id ? null : j.id)} style={{ cursor: "pointer" }}>
                  <td>{data.kinds[j.kind] ?? j.kind}</td>
                  <td><StatusDot status={j.status} />{jobStatus(j.status)}</td>
                  <td style={{ minWidth: 200 }}>{j.status === "running" ? <><div className="progress"><i style={{ width: `${j.progress * 100}%` }} /></div><span className="small muted">{j.message}</span></> : <span className="small muted">{j.message}</span>}</td>
                  <td className="muted small">{ago(j.started)}</td>
                  <td className="muted small">{j.started && j.finished ? `${Math.round(j.finished - j.started)} s` : ""}</td>
                </tr>
                {open === j.id && (j.log || j.error) && <tr className="detail"><td colSpan={5}><pre className="log">{j.error ?? j.log}</pre></td></tr>}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function SwapsTab() {
  return (
    <>
      <p className="lede">{t("Swaps to smaller versions, started from «Find a smaller version» or the Swap quality page. They are followed up every 5 minutes, and more often while this page is open.",
        "Bytter til mindre versjoner, startet fra «Finn mindre versjon» eller siden Bytt kvalitet. De følges opp hvert 5. minutt, og oftere mens denne siden er åpen.")}</p>
      <SwapList empty={t("No swaps have been started.", "Ingen bytter er startet.")} />
    </>
  );
}

type Action = { id: number; ts: number; title: string; action: string; service: string | null; status: string; detail: string; bytes: number };

function LogTab() {
  const tick = useRefreshTick();
  const { data, error } = useFetch<{ items: Action[]; enabled: boolean; files_enabled: boolean }>("/api/actions/history", [tick]);
  const done = data?.items.filter((a) => a.status === "done") ?? [];
  const total = done.reduce((s, a) => s + (a.bytes || 0), 0);
  const actionText = (a: string) => ({
    delete_title: t("Whole title", "Hel tittel"), delete_season: t("Season", "Sesong"), delete_file: t("Duplicate file", "Duplikatfil"),
    delete_download: t("Download", "Nedlasting"), delete_folder: t("Folder on disk", "Mappe på disk"), plex_remove: t("Removed from Plex", "Fjernet fra Plex"),
  } as Record<string, string>)[a] ?? a;
  const serviceText = (s: string | null) => s === "radarr" ? "Radarr" : s === "sonarr" ? "Sonarr" : s === "plex" ? "Plex" : s === "disk" || s === "filsystem" ? t("disk", "disk") : s ?? "";
  return (
    <>
      <p className="lede">{t("Everything the app has deleted or changed, with the result.", "Alt appen har slettet eller endret, med resultat.")}
        {data && !data.enabled && !data.files_enabled && t(" Deletion is switched off now.", " Sletting er slått av nå.")}</p>
      <ErrorNote error={error} />
      {data && data.items.length === 0 && <div className="empty">{t("Nothing has been deleted from the app yet.", "Ingenting er slettet fra appen ennå.")}</div>}
      {data && data.items.length > 0 && (
        <>
          <p className="small muted">{t(`${done.length} done, about ${bytes(total)} freed.`, `${done.length} utført, omtrent ${bytes(total)} frigjort.`)}</p>
          <div className="table-wrap">
            <table>
              <thead><tr><th>{t("Time", "Tidspunkt")}</th><th>{t("What", "Hva")}</th><th>{t("Status", "Status")}</th><th>{t("Details", "Detaljer")}</th><th className="r">{t("Space", "Plass")}</th></tr></thead>
              <tbody>
                {data.items.map((a) => (
                  <tr key={a.id}>
                    <td className="small muted num">{new Date(a.ts * 1000).toLocaleString(locale())}</td>
                    <td>{a.title}<div className="small faint">{actionText(a.action)}{a.service ? `, ${serviceText(a.service)}` : ""}</div></td>
                    <td><StatusDot status={a.status} />{statusLabel(a.status)}</td>
                    <td className="small muted">{a.detail}</td>
                    <td className="r num">{a.status === "done" && a.bytes ? bytes(a.bytes) : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  );
}
