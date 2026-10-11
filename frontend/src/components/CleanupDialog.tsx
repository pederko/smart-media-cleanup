import { useEffect, useState } from "react";
import { api } from "../api";
import { bytes, fileName } from "../format";
import { plural, t } from "../i18n";
import { Drawer, Loading, statusLabel, StatusDot, SwitchedOff } from "./common";

type PlanItem = { key: string; name: string; ok: boolean; reason: string | null; folder?: string; size: number; freed?: number;
  files: { path: string; size: number }[]; calls?: { rating_key: string; media_id: string | null; label: string; whole?: boolean }[]; kept?: number };
type Plan = { enabled: boolean; items: PlanItem[]; count: number; token: string; freed?: number; files?: number; calls?: number };
type Res = { results: { key: string; status: string; detail: string }[]; done: number; failed: number };

/**
 * mode «disk»: delete folders that only exist on disk (not in Radarr, Sonarr or Plex).
 * mode «plex»: remove Plex entries whose files are missing on disk.
 */
export default function CleanupDialog({ mode, keys, onClose, onDone }: { mode: "disk" | "plex"; keys: string[]; onClose: () => void; onDone: () => void }) {
  const base = mode === "disk" ? "/api/plex-check/delete" : "/api/plex-check/remove";
  const [plan, setPlan] = useState<Plan | null>(null);
  const [res, setRes] = useState<Res | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  useEffect(() => { api.post<Plan>(`${base}/plan`, { keys }).then(setPlan).catch((e) => setError(String(e.message))); }, [keys, base]);
  const run = async () => {
    if (!plan) return;
    setBusy(true); setError(null);
    try { setRes(await api.post<Res>(`${base}/execute`, { keys, token: plan.token })); onDone(); }
    catch (e) { setError(String((e as Error).message)); } finally { setBusy(false); }
  };
  const ok = plan?.items.filter((i) => i.ok) ?? [];
  const no = plan?.items.filter((i) => !i.ok) ?? [];
  const names = Object.fromEntries((plan?.items ?? []).map((i) => [i.key, i.name]));
  const titles = (n: number) => plural(n, ["title", "titles"], ["tittel", "titler"]);
  const folders = (n: number) => plural(n, ["folder", "folders"], ["mappe", "mapper"]);
  return (
    <Drawer label={mode === "disk" ? t("Delete from disk", "Slett fra disk") : t("Remove from Plex", "Fjern fra Plex")} onClose={onClose} busy={busy}>
      {res ? (
        <>
          <h1>{res.failed ? t("Partly done", "Delvis fullført") : t("Done", "Ferdig")}</h1>
          <p className="lede">{mode === "disk"
            ? t(`${folders(res.done)} deleted from disk. A full refresh has started.`, `${folders(res.done)} slettet fra disk. En full oppdatering er startet.`)
            : t(`${titles(res.done)} removed from Plex. A sync has started.`, `${titles(res.done)} fjernet fra Plex. En synk er startet.`)}</p>
          <table className="compact"><tbody>{res.results.map((r) => <tr key={r.key}><td><StatusDot status={r.status} />{names[r.key] ?? r.key}</td><td className="small muted">{statusLabel(r.status)}: {r.detail}</td></tr>)}</tbody></table>
          <p><button className="btn primary" onClick={onClose}>{t("Done", "Ferdig")}</button></p>
        </>
      ) : (
        <>
          <h1>{mode === "disk" ? t(`Delete ${folders(ok.length)} from disk`, `Slett ${folders(ok.length)} fra disk`) : t(`Remove ${titles(ok.length)} from Plex`, `Fjern ${titles(ok.length)} fra Plex`)}</h1>
          {error && <div className="notice err">{error}</div>}
          {!plan ? <Loading /> : !plan.enabled ? <SwitchedOff what={mode === "disk" ? "files" : "services"} onClose={onClose} /> : (
            <>
              <p className="lede">{ok.length === 0 ? t("None of the selected can be included.", "Ingen av de valgte kan tas med.") : mode === "disk"
                ? <>{t(`The folders are deleted from disk with all content (${plural(plan.files ?? 0, ["file", "files"], ["fil", "filer"])}).`, `Mappene slettes fra disk med alt innhold (${plural(plan.files ?? 0, ["file", "files"], ["fil", "filer"])}).`)} <b>{bytes(plan.freed ?? 0)}</b> {t("is freed. They are not in Radarr, Sonarr or Plex. This cannot be undone.", "frigjøres. De ligger verken i Radarr, Sonarr eller Plex. Dette kan ikke angres.")}</>
                : t("The entries are removed from the Plex library. The files do not exist on disk, so nothing is deleted there. Watch history in Tautulli is kept.",
                  "Oppføringene fjernes fra Plex-biblioteket. Filene finnes ikke på disk, så ingenting slettes der. Seerhistorikken i Tautulli beholdes.")}</p>
              {mode === "plex" && ok.length > 0 && <p className="small muted">{t("Right before each call the app checks that none of the files exist. Requires «Allow media deletion» in Plex → Settings → Library.",
                "Rett før hvert kall sjekker appen at ingen av filene finnes. Krever «Allow media deletion» i Plex → Settings → Library.")}</p>}
              <table className="compact"><tbody>{ok.map((i) => (
                <tr key={i.key}>
                  <td>
                    <button className="linkish" onClick={() => setOpen(open === i.key ? null : i.key)}>{i.name}</button>
                    <div className="small muted">{mode === "disk" ? i.folder
                      : i.calls!.some((c) => c.whole) ? t("The whole series", "Hele serien")
                        : `${plural(i.calls!.length, ["entry", "entries"], ["oppføring", "oppføringer"])}${i.kept ? t(`, ${i.kept} existing file(s) kept`, `, ${i.kept} fil(er) som finnes beholdes`) : ""}`}</div>
                    {open === i.key && <ul className="small muted" style={{ paddingLeft: 16, margin: "4px 0" }}>
                      {mode === "disk" ? i.files.map((f) => <li key={f.path}>{fileName(f.path)} ({bytes(f.size)})</li>) : i.calls!.map((c) => <li key={c.rating_key + c.media_id}>{c.label}</li>)}
                    </ul>}
                  </td>
                  <td className="r num">{mode === "disk" ? bytes(i.freed ?? 0) : ""}</td>
                </tr>
              ))}</tbody></table>
              {no.length > 0 && <details style={{ marginTop: 12 }} open={ok.length === 0}><summary className="small muted">{t(`${no.length} not included`, `${no.length} tas ikke med`)}</summary><ul className="conseq small">{no.map((i) => <li key={i.key}>{i.name}: {i.reason}</li>)}</ul></details>}
              {ok.length > 0 && <p style={{ marginTop: 20 }}><button className="btn danger" onClick={run} disabled={busy}>{busy ? t("Working…", "Arbeider…") : mode === "disk"
                ? t(`Delete ${folders(ok.length)} from disk (${bytes(plan.freed ?? 0)})`, `Slett ${folders(ok.length)} fra disk (${bytes(plan.freed ?? 0)})`)
                : t(`Remove ${titles(ok.length)} from Plex`, `Fjern ${titles(ok.length)} fra Plex`)}</button></p>}
            </>
          )}
        </>
      )}
    </Drawer>
  );
}
